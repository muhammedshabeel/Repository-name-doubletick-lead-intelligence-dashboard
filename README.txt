1. Paste one customer number per line into phone_numbers.txt.
2. Open Terminal.
3. Run:
   cd ~/Downloads/doubletick_ad_id_report_simple
   chmod +x run.command
   ./run.command
4. Paste the API key when asked. Typing is hidden.
5. Press Enter to use WABA 971521367907.
6. Paste a Meta access token to resolve Ad ID into Ad, Ad Set and Campaign names. Press Enter to skip.
7. Enter start and inclusive end dates in DD-MM-YYYY.

Output: doubletick_ad_id_report.xlsx
The script tries customer numbers both with and without +.
It automatically adds one day to the API end date so the selected final day is included.
Meta tokens need permission to read the ad accounts containing the returned Ad IDs.
Required Meta permission: ads_read (or ads_management) and access to every relevant ad account.
Check meta_lookup_status and meta_error in All_Chats when a campaign name is missing.
