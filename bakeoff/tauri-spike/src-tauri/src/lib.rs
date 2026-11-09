use std::io::{Read, Write};
use std::net::TcpListener;
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::Mutex;
use tauri::{Manager, RunEvent, WebviewUrl, WebviewWindowBuilder};
use window_vibrancy::{apply_vibrancy, NSVisualEffectMaterial};

/// The brain's stdin is its lifeline: holding it keeps the brain alive, and the
/// pipe closing (normal quit or a killed shell) makes the brain shut down.
struct Brain {
  _child: Child,
  _stdin: ChildStdin,
}

fn free_port() -> u16 {
  TcpListener::bind("127.0.0.1:0").unwrap().local_addr().unwrap().port()
}

fn token() -> String {
  let mut buf = [0u8; 16];
  std::fs::File::open("/dev/urandom").unwrap().read_exact(&mut buf).unwrap();
  buf.iter().map(|b| format!("{b:02x}")).collect()
}

fn spawn_brain(port: u16, token: &str) -> Brain {
  let root = concat!(env!("CARGO_MANIFEST_DIR"), "/..");
  let mut child = Command::new("uv")
    .args(["run", "--project", &format!("{root}/../bench"), "python", &format!("{root}/brain/brain.py")])
    .stdin(Stdio::piped())
    .spawn()
    .expect("failed to start brain");
  let mut stdin = child.stdin.take().unwrap();
  writeln!(stdin, "{{\"port\": {port}, \"token\": \"{token}\"}}").unwrap();
  stdin.flush().unwrap();
  Brain { _child: child, _stdin: stdin }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
  let app = tauri::Builder::default()
    .setup(|app| {
      let (port, token) = (free_port(), token());
      let bench = std::env::var("GAMBIT_BENCH").is_ok();
      app.manage(Mutex::new(Some(spawn_brain(port, &token))));
      let window = WebviewWindowBuilder::new(app, "main", WebviewUrl::default())
        .title("gambit")
        .inner_size(1360.0, 860.0)
        .min_inner_size(1080.0, 720.0)
        .title_bar_style(tauri::TitleBarStyle::Overlay)
        .hidden_title(true)
        .transparent(true)
        .initialization_script(&format!("window.__GAMBIT__ = {{ port: {port}, token: '{token}', bench: {bench} }};"))
        .build()?;
      apply_vibrancy(&window, NSVisualEffectMaterial::Sidebar, None, None)
        .expect("vibrancy is macOS-only");
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
