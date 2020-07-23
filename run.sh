#!/bin/bash
# Restarts bot automatically unless closed through ctrl+C
# Utilizes venv for Python 3

# Move into directory of this bash script if not already
MAIN_DIR="${0%/*}"
if [[ $MAIN_DIR != "run.sh" ]]
then
  echo "Not in correct dir: '$PWD'  Moving to relative dir: '$MAIN_DIR'"
  cd "${0%/*}"
fi
echo "In correct dir: '$PWD'"

LOGFILE=$PWD/restart.log
LOOPER=true

writelog() {
  now=`date`
  echo "$*"
  echo "$now $*" >> $LOGFILE
}

ctrl_c() {
    LOOPER=false
    writelog "Exited with status $?"
    writelog "Closing!"
    exit
}

trap ctrl_c INT

writelog "Starting..."
source venv/bin/activate
writelog "Activated venv..."
cd osrs-event-log
writelog "cd into osrs-event-log..."
while $LOOPER ; do
  python osrs-event-log.py
  writelog "Exited with status $?"
  writelog "Restarting..."
done