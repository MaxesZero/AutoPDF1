# AutoPDF Telegram Bot

A Telegram bot that helps fill PDF forms automatically. It retrieves PDF templates from Google Drive, collects data via conversation, stores it in Google Sheets, and sends back the filled PDFs.

## Features

- Interactive Telegram bot interface
- PDF template selection from Google Drive
- Automatic form field detection in PDF templates
- Data collection via conversation
- Google Sheets integration for data storage
- PDF form filling
- Automatic sending of generated PDFs to users

## Requirements

- Python 3.7+
- Telegram Bot API token
- Google Cloud credentials (service account with access to Sheets and Drive)
- PDF templates with form fields uploaded to Google Drive

## Installation

1. Clone this repository:
   ```
   git clone https://github.com/yourusername/AutoPDF.git
   cd AutoPDF
   ```

2. Create and activate a virtual environment:
   ```
   python -m venv venv
   source venv/bin/activate   # On Windows: venv\Scripts\activate
   ```

3. Install required packages:
   ```
   pip install -r requirements.txt
   ```

4. Create a `.env` file with your tokens:
   ```
   TELEGRAM_TOKEN=your_telegram_token_here
   SPREADSHEET_ID=your_google_sheet_id_here
   ```

5. Place your Google credentials JSON file in the project root as `google_credentials.json`

6. Upload your PDF templates with form fields to Google Drive using the same Google account

## Usage

1. Start the bot:
   ```
   python autopdf_bot.py
   ```

2. In Telegram, find your bot and start a conversation with `/start`

3. Start filling a form with `/fill` and follow these steps:
   - Select a PDF template from your Google Drive
   - The bot will identify the form fields in the template
   - Fill in each field as prompted
   - When complete, the bot will generate and send the filled PDF

4. The data will also be saved to your Google Sheet for record-keeping

## PDF Template Requirements

The PDF templates should have fillable form fields. These can be created using:
- Adobe Acrobat Pro
- PDFescape (online)
- LibreOffice Draw
- Other PDF editing tools that support form fields

Each form field should have a unique name which will be detected by the bot.

## Google Setup

### Service Account

1. Go to the [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project (or select an existing one)
3. Enable the Google Sheets API and Google Drive API
4. Create a service account with Editor permissions
5. Create and download a JSON key for this service account
6. Save the JSON file as `google_credentials.json` in your project root

### Google Drive

1. Upload your PDF templates to Google Drive
2. Share them with the service account email (it looks like: `something@project-id.iam.gserviceaccount.com`)

### Google Sheets

1. Create a new Google Sheet for data storage
2. Share it with the service account email
3. Copy the Sheet ID from the URL (the long string between /d/ and /edit in the URL)
4. Add this ID to your `.env` file as `SPREADSHEET_ID`

## License

MIT

## Author

Your Name 