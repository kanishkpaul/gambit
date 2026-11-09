#!/bin/zsh
APP=./tauri-spike/src-tauri/target/release/app; R=bench/results/lifecycle_gui.txt; : > $R
count() { echo "brain=$(pgrep -f brain/brain.py | wc -l | tr -d ' ') stockfish=$(pgrep -x stockfish | wc -l | tr -d ' ')"; }
launch() { rm -f bench/results/tauri_frames.json; GAMBIT_BENCH=1 $APP >/dev/null 2>&1 & APP_PID=$!
  for i in {1..60}; do [ -f bench/results/tauri_frames.json ] && break; sleep 1; done; sleep 1; }
front() { osascript -e "tell application \"System Events\" to set frontmost of (first process whose unix id is $APP_PID) to true" -e 'delay 1'; }
for attempt in 1 2; do
  launch; front; osascript -e 'tell application "System Events" to keystroke "q" using command down'; sleep 2
  echo "Cmd-Q #$attempt: shell alive=$(kill -0 $APP_PID 2>/dev/null && echo yes || echo no) $(count)" >> $R
  kill -9 $APP_PID 2>/dev/null; sleep 2; pkill -x stockfish; pkill -f brain/brain.py
  launch; front; osascript -e "tell application \"System Events\" to click (first button whose subrole is \"AXCloseButton\") of front window of (first process whose unix id is $APP_PID)"; sleep 2
  echo "Close window #$attempt: shell alive=$(kill -0 $APP_PID 2>/dev/null && echo yes || echo no) $(count)" >> $R
  kill -9 $APP_PID 2>/dev/null; sleep 2; pkill -x stockfish; pkill -f brain/brain.py
done
cat $R
