#!/bin/bash
set -e
cd "$(dirname "$0")"
if [ ! -d env ]; then
  python3 -m venv env
  source env/bin/activate
  python3 -m pip install --upgrade pip
  python3 -m pip install -r requirements.txt
else
  source env/bin/activate
fi
if [ -z "$DOUBLETICK_API_KEY" ]; then read -s -p "Paste DoubleTick API key: " DOUBLETICK_API_KEY; echo; export DOUBLETICK_API_KEY; fi
if [ -z "$DOUBLETICK_WABA_NUMBERS" ]; then read -p "WABA number [971521367907]: " DOUBLETICK_WABA_NUMBERS; DOUBLETICK_WABA_NUMBERS=${DOUBLETICK_WABA_NUMBERS:-971521367907}; export DOUBLETICK_WABA_NUMBERS; fi
if [ -z "$META_ACCESS_TOKEN" ]; then
  read -s -p "Paste Meta access token, or press Enter to skip: " META_ACCESS_TOKEN
  echo
  export META_ACCESS_TOKEN
fi
read -p "Start date DD-MM-YYYY: " START
read -p "End date DD-MM-YYYY (inclusive): " END
if [ ! -s phone_numbers.txt ]; then echo "phone_numbers.txt is empty."; exit 1; fi
python3 doubletick_ad_id_report.py --input phone_numbers.txt --start-date "$START" --end-date "$END" --workers 8
echo "Created: doubletick_ad_id_report.xlsx"
read -p "Press Enter to close..."
