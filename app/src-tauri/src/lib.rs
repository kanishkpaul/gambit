//! gambit's shell. Kept thin: windows, menus, the Keychain, and supervising the Python brain.
//!
//! Secrets (the Lichess token) flow Keychain → Rust → brain stdin. They never enter the WebView, and the brain never
//! touches the Keychain. The brain's stdin is also its lifeline: when the shell exits for any
//! reason the pipe closes and the brain shuts its engines down.

use std::io::{Read, Write};
use std::net::TcpListener;
use std::path::PathBuf;
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::Mutex;

use serde_json::json;
use tauri::menu::{AboutMetadata, MenuBuilder, MenuItemBuilder, PredefinedMenuItem, SubmenuBuilder};
use tauri::{Emitter, Manager, RunEvent, WebviewUrl, WebviewWindowBuilder};
use window_vibrancy::{apply_vibrancy, NSVisualEffectMaterial};

const KEYCHAIN_SERVICE: &str = "dev.kanishkpaul.gambit";
const SECRETS: [&str; 1] = ["lichess_token"];

struct Brain {
  _child: Child,
  stdin: ChildStdin,
}

fn free_port() -> u16 {
  TcpListener::bind("127.0.0.1:0").unwrap().local_addr().unwrap().port()
}

fn random_token() -> String {
  let mut buf = [0u8; 16];
  std::fs::File::open("/dev/urandom").unwrap().read_exact(&mut buf).unwrap();
  buf.iter().map(|b| format!("{b:02x}")).collect()
}

fn read_secret(name: &str) -> Option<String> {
  keyring::Entry::new(KEYCHAIN_SERVICE, name).ok()?.get_password().ok()
}

fn home() -> PathBuf {
  PathBuf::from(std::env::var("HOME").unwrap_or_default())
}

/// Apps launched from Finder get a minimal PATH; make uv and Stockfish findable.
fn child_path() -> String {
  let mut dirs = vec![home().join(".local/bin"), PathBuf::from("/opt/homebrew/bin"), PathBuf::from("/usr/local/bin")];
  dirs.extend(std::env::split_paths(&std::env::var("PATH").unwrap_or_default()));
  std::env::join_paths(dirs).unwrap().to_string_lossy().into_owned()
}

fn brain_dir() -> PathBuf {
  std::env::var("GAMBIT_BRAIN_DIR")
    .map(PathBuf::from)
    .unwrap_or_else(|_| PathBuf::from(concat!(env!("CARGO_MANIFEST_DIR"), "/../../brain")))
}

/// In a release build the brain's output goes to ~/Library/Logs/dev.kanishkpaul.gambit/brain.log
/// (a Finder-launched app has no terminal); `tauri dev` keeps it in the terminal.
fn brain_log(app: &tauri::App) -> Option<std::fs::File> {
  if cfg!(debug_assertions) {
    return None;
  }
  let dir = app.path().app_log_dir().ok()?;
  std::fs::create_dir_all(&dir).ok()?;
  std::fs::File::create(dir.join("brain.log")).ok()
}

fn spawn_brain(port: u16, ws_token: &str, log: Option<&std::fs::File>) -> std::io::Result<Brain> {
  let dir = brain_dir();
  if !dir.join("pyproject.toml").exists() {
    return Err(std::io::Error::other(format!("no brain at {} (set GAMBIT_BRAIN_DIR if the repo moved)", dir.display())));
  }
  let out = |f: Option<&std::fs::File>| f.and_then(|f| f.try_clone().ok()).map(Stdio::from).unwrap_or_else(Stdio::inherit);
  let mut child = Command::new("uv")
    .env("PATH", child_path())
    .args(["run", "--frozen", "--project"])
    .arg(&dir)
    .args(["python", "-m", "gambit_brain"])
    .current_dir(&dir)
    .stdin(Stdio::piped())
    .stdout(out(log))
    .stderr(out(log))
    .spawn()?;
  let mut stdin = child.stdin.take().expect("piped stdin");
  let mut init = json!({ "port": port, "ws_token": ws_token });
  for name in SECRETS {
    if let Some(v) = read_secret(name) {
      init[name] = json!(v);
    }
  }
  writeln!(stdin, "{init}")?;
  stdin.flush()?;
  Ok(Brain { _child: child, stdin })
}

/// Store (or with an empty value, delete) a secret in the Keychain and hand it to the brain.
#[tauri::command]
fn set_secret(name: String, value: String, brain: tauri::State<Mutex<Option<Brain>>>) -> Result<(), String> {
  if !SECRETS.contains(&name.as_str()) {
    return Err(format!("unknown secret {name}"));
  }
  let entry = keyring::Entry::new(KEYCHAIN_SERVICE, &name).map_err(|e| e.to_string())?;
  let value = value.trim().to_string();
  if value.is_empty() {
    match entry.delete_credential() {
      Ok(()) | Err(keyring::Error::NoEntry) => {}
      Err(e) => return Err(e.to_string()),
    }
  } else {
    entry.set_password(&value).map_err(|e| e.to_string())?;
  }
  if let Some(b) = brain.lock().unwrap().as_mut() {
    let line = json!({ "secrets": { name: value } });
    writeln!(b.stdin, "{line}").and_then(|_| b.stdin.flush()).map_err(|e| e.to_string())?;
  }
  Ok(())
}

fn build_menu(app: &tauri::App) -> tauri::Result<tauri::menu::Menu<tauri::Wry>> {
  let settings = MenuItemBuilder::with_id("settings", "Settings…").accelerator("CmdOrCtrl+,").build(app)?;
  let palette = MenuItemBuilder::with_id("palette", "Command Palette…").accelerator("CmdOrCtrl+K").build(app)?;
  let app_menu = SubmenuBuilder::new(app, "gambit")
    .item(&PredefinedMenuItem::about(app, Some("About gambit"), Some(AboutMetadata::default()))?)
    .separator()
    .item(&settings)
    .separator()
    .services()
    .separator()
    .hide()
    .hide_others()
    .show_all()
    .separator()
    .quit()
    .build()?;
  let edit = SubmenuBuilder::new(app, "Edit").undo().redo().separator().cut().copy().paste().select_all().build()?;
  let view = SubmenuBuilder::new(app, "View").item(&palette).separator().fullscreen().build()?;
  let window = SubmenuBuilder::new(app, "Window").minimize().maximize().separator().close_window().build()?;
  MenuBuilder::new(app).items(&[&app_menu, &edit, &view, &window]).build()
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
  let app = tauri::Builder::default()
    .plugin(tauri_plugin_opener::init())
    .manage(Mutex::new(None::<Brain>))
    .invoke_handler(tauri::generate_handler![set_secret])
    .setup(|app| {
      let (port, ws_token) = (free_port(), random_token());
      let log = brain_log(app);
      let brain = spawn_brain(port, &ws_token, log.as_ref()).map_err(|e| {
        let msg = format!("couldn't start the brain (is uv installed?): {e}");
        if let Some(mut f) = log.as_ref() {
          let _ = writeln!(f, "shell: {msg}");
        }
        msg
      })?;
      *app.state::<Mutex<Option<Brain>>>().lock().unwrap() = Some(brain);

      app.set_menu(build_menu(app)?)?;
      app.on_menu_event(|handle, event| {
        let id = event.id().as_ref();
        if id == "settings" || id == "palette" {
          let _ = handle.emit("menu", id);
        }
      });

      let window = WebviewWindowBuilder::new(app, "main", WebviewUrl::default())
        .title("gambit")
        .inner_size(1360.0, 860.0)
        .min_inner_size(1080.0, 720.0)
        .title_bar_style(tauri::TitleBarStyle::Overlay)
        .hidden_title(true)
        .transparent(true)
        .initialization_script(format!("window.__GAMBIT__ = {{ port: {port}, token: '{ws_token}' }};"))
        .build()?;
      apply_vibrancy(&window, NSVisualEffectMaterial::Sidebar, None, None).expect("vibrancy is macOS-only");
      Ok(())
    })
    .build(tauri::generate_context!())
    .expect("error while building tauri application");

  app.run(|handle, event| {
    if let RunEvent::Exit = event {
      // Dropping the brain closes its stdin; the brain stops its engines and exits.
      handle.state::<Mutex<Option<Brain>>>().lock().unwrap().take();
    }
  });
}
