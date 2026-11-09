#!/bin/zsh
# Quit-path torture: launch the spike with 4 busy Stockfish workers, end it one way, count orphans.
APP=./tauri-spike/src-tauri/target/release/app
R=bench/results/lifecycle.txt; : > $R
orphans() { pgrep -f "brain/brain.py" | wc -l | tr -d ' '; }
engines() { pgrep -x stockfish | wc -l | tr -d ' '; }
launch() {
  rm -f bench/results/tauri_frames.json
  GAMBIT_BENCH=1 $APP >/dev/null 2>&1 &
  APP_PID=$!
  for i in {1..60}; do [ -f bench/results/tauri_frames.json ] && break; sleep 1; done
  echo "  before: brain=$(orphans) stockfish=$(engines)" >> $R
}
check() { sleep 2; echo "$1: after 2s brain=$(orphans) stockfish=$(engines)" >> $R; pkill -x stockfish; pkill -f brain/brain.py; }

launch; osascript -e 'tell application "System Events" to tell (first process whose unix id is '$APP_PID') to set frontmost to true' -e 'delay 0.5' -e 'tell application "System Events" to keystroke "q" using command down'; check "Cmd-Q"
launch; osascript -e 'tell application "System Events" to tell (first process whose unix id is '$APP_PID') to click button 1 of window 1'; check "Close window"
launch; kill -TERM $APP_PID; check "SIGTERM shell"
launch; kill -9 $APP_PID; check "kill -9 shell"
launch; osascript -e 'tell application "app" to quit'; sleep 0.5; echo "  shell alive after quit event: $(kill -0 $APP_PID 2>/dev/null && echo yes || echo no)" >> $R; check "Apple-event quit"
cat $R
