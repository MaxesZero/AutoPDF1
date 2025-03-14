#!/usr/bin/env python3
# AutoPDF Bot - A Telegram bot that collects data and fills PDF templates

import os
import logging
from typing import Dict, List, Optional, Tuple
import json
import io
from datetime import datetime
from dotenv import load_dotenv

# Telegram imports
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application, 
    CommandHandler, 
    ContextTypes, 
    MessageHandler, 
    filters,
    ConversationHandler,
    CallbackContext
)

# Google Sheets integration
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

# PDF processing
from pdfrw2 import PdfReader, PdfWriter, IndirectPdfDict
import pdfrw2.coreutils

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# States for conversation handler
CHOOSING, TYPING_REPLY, TEMPLATE_SELECTION = range(3)

# Default invoice fields
DEFAULT_FIELDS = [
    'client_name', 
    'client_email', 
    'invoice_number', 
    'invoice_date', 
    'due_date', 
    'amount', 
    'description'
]

# Configuration from environment
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
SPREADSHEET_ID = os.environ.get('SPREADSHEET_ID')
CREDENTIALS_FILE = os.environ.get('GOOGLE_CREDENTIALS_FILE', 'google_credentials.json')
OUTPUT_DIR = os.environ.get('OUTPUT_DIR', 'generated')

# Validate required configuration
if not TELEGRAM_TOKEN:
    raise ValueError("No TELEGRAM_TOKEN found in environment variables. Please set it in .env file.")

# Google API setup
SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive'
]

def setup_google_services():
    """Set up Google Sheets and Drive clients with credentials"""
    try:
        if not os.path.exists(CREDENTIALS_FILE):
            logger.warning(f"Google credentials file not found: {CREDENTIALS_FILE}")
            return None, None
            
        creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=SCOPES)
        sheets_client = gspread.authorize(creds)
        drive_service = build('drive', 'v3', credentials=creds)
        return sheets_client, drive_service
    except Exception as e:
        logger.error(f"Error setting up Google services: {e}")
        return None, None

def ensure_sheet_headers(sheet, headers):
    """Ensure the Google Sheet has the correct headers"""
    try:
        # Check if the sheet is empty
        cell_list = sheet.get_all_values()
        if not cell_list:
            # Add headers if the sheet is empty
            sheet.append_row(headers + ['Timestamp'])
            logger.info("Added headers to empty Google Sheet")
    except Exception as e:
        logger.error(f"Error ensuring sheet headers: {e}")

def list_pdf_templates():
    """List all PDF templates in Google Drive"""
    try:
        _, drive_service = setup_google_services()
        if not drive_service:
            return []
            
        # Search for PDF files
        query = "mimeType='application/pdf'"
        results = drive_service.files().list(
            q=query, 
            spaces='drive',
            fields='files(id, name)'
        ).execute()
        
        templates = results.get('files', [])
        return templates
    except Exception as e:
        logger.error(f"Error listing PDF templates: {e}")
        return []

def download_template_from_drive(template_id):
    """Download a PDF template from Google Drive"""
    try:
        _, drive_service = setup_google_services()
        if not drive_service:
            return None
            
        # Get file metadata
        file = drive_service.files().get(fileId=template_id).execute()
        
        # Create a BytesIO object to store the downloaded file
        file_content = io.BytesIO()
        
        # Download the file
        request = drive_service.files().get_media(fileId=template_id)
        downloader = MediaIoBaseDownload(file_content, request)
        
        done = False
        while not done:
            status, done = downloader.next_chunk()
            
        file_content.seek(0)
        return file_content, file['name']
    except Exception as e:
        logger.error(f"Error downloading template: {e}")
        return None, None

def extract_pdf_form_fields(template_content):
    """Extract form fields from a PDF template"""
    try:
        template = PdfReader(template_content)
        fields = []
        
        # Iterate through pages to find form fields
        for page in template.pages:
            annotations = page.get('/Annots')
            if annotations:
                for annotation in annotations:
                    if annotation['/Subtype'] == '/Widget' and annotation['/FT'] == '/Tx':
                        field_name = annotation['/T']
                        if field_name:
                            fields.append(field_name)
        
        return list(set(fields)), template  # Remove duplicates
    except Exception as e:
        logger.error(f"Error extracting PDF form fields: {e}")
        return [], None

def generate_pdf(data: Dict[str, str], template, output_path: str) -> bool:
    """
    Generate a PDF by filling a template with data
    
    Args:
        data: Dictionary with field names and values
        template: PdfReader object with the template
        output_path: Path where to save the generated PDF
        
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        # Get the form fields from the template
        for page in template.pages:
            annotations = page.get('/Annots')
            if annotations:
                for annotation in annotations:
                    if annotation['/Subtype'] == '/Widget' and annotation['/FT'] == '/Tx':
                        field_name = annotation['/T']
                        if field_name in data:
                            annotation.update(
                                pdfrw2.IndirectPdfDict(
                                    V=data[field_name],
                                    AS=data[field_name]
                                )
                            )
        
        # Write the filled PDF
        PdfWriter().write(output_path, template)
        return True
    except Exception as e:
        logger.error(f"Error generating PDF: {e}")
        return False

# Save data to Google Sheets
async def save_to_sheets(data: Dict[str, str], headers: List[str]) -> bool:
    """Save form data to Google Sheets"""
    try:
        if not SPREADSHEET_ID:
            logger.warning("No SPREADSHEET_ID provided. Skipping Google Sheets integration.")
            return False
            
        sheets_client, _ = setup_google_services()
        if not sheets_client:
            return False
            
        sheet = sheets_client.open_by_key(SPREADSHEET_ID).sheet1
        
        # Ensure sheet has headers
        ensure_sheet_headers(sheet, headers)
        
        # Prepare row data
        row = [data.get(field, '') for field in headers] + [datetime.now().strftime('%Y-%m-%d %H:%M:%S')]
        
        # Append row to sheet
        sheet.append_row(row)
        logger.info(f"Added form data to Google Sheets")
        return True
    except Exception as e:
        logger.error(f"Error saving to Google Sheets: {e}")
        return False

# Command handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a message when the command /start is issued."""
    user = update.effective_user
    await update.message.reply_text(
        f"Hi {user.first_name}! I'm AutoPDF Bot. I help you fill PDF forms automatically.\n\n"
        f"Use /fill to start filling a PDF template.\n"
        f"Use /help to see available commands."
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a message when the command /help is issued."""
    await update.message.reply_text(
        "Here's how to use this bot:\n\n"
        "/start - Start the bot\n"
        "/fill - Fill a PDF template\n"
        "/help - Show this help message\n"
        "/cancel - Cancel the current operation"
    )

# PDF filling conversation handlers
async def fill_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start the PDF filling process by offering template selection"""
    # Get available templates from Google Drive
    templates = list_pdf_templates()
    
    if not templates:
        await update.message.reply_text(
            "No PDF templates found in your Google Drive. Please upload at least one PDF form template."
        )
        return ConversationHandler.END
    
    context.user_data['templates'] = templates
    
    # Create keyboard with template options
    reply_keyboard = [[template['name']] for template in templates]
    
    await update.message.reply_text(
        "Let's fill a PDF form. Please select a template:",
        reply_markup=ReplyKeyboardMarkup(
            reply_keyboard, one_time_keyboard=True
        ),
    )
    
    return TEMPLATE_SELECTION

async def template_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle template selection"""
    selected_template_name = update.message.text
    templates = context.user_data.get('templates', [])
    
    # Find the selected template
    selected_template = next((t for t in templates if t['name'] == selected_template_name), None)
    
    if not selected_template:
        await update.message.reply_text(
            "Sorry, I couldn't find that template. Please try again."
        )
        return ConversationHandler.END
    
    # Download template and extract form fields
    template_content, _ = download_template_from_drive(selected_template['id'])
    
    if not template_content:
        await update.message.reply_text(
            "Sorry, I couldn't download the template. Please check permissions and try again."
        )
        return ConversationHandler.END
    
    # Extract fields from template
    fields, template = extract_pdf_form_fields(template_content)
    
    if not fields:
        await update.message.reply_text(
            "No fillable fields found in this template. Please select a PDF with form fields."
        )
        return ConversationHandler.END
    
    # Save template details in user data
    context.user_data['form_data'] = {}
    context.user_data['template_id'] = selected_template['id']
    context.user_data['template_name'] = selected_template_name
    context.user_data['fields'] = fields
    context.user_data['template'] = template
    context.user_data['template_content'] = template_content
    
    # Create keyboard with field options
    reply_keyboard = [[field] for field in fields]
    
    await update.message.reply_text(
        f"Selected template: {selected_template_name}\n\n"
        f"Found {len(fields)} fillable fields. Please choose a field to fill:",
        reply_markup=ReplyKeyboardMarkup(
            reply_keyboard, one_time_keyboard=True
        ),
    )
    
    return CHOOSING

async def regular_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Ask the user for info about the selected field."""
    text = update.message.text
    context.user_data['choice'] = text
    
    await update.message.reply_text(
        f"Please enter the value for field '{text}':",
        reply_markup=ReplyKeyboardRemove(),
    )
    
    return TYPING_REPLY

async def received_information(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Store user info and ask for the next field."""
    text = update.message.text
    field = context.user_data['choice']
    context.user_data['form_data'][field] = text
    
    # Check if all fields are filled
    if len(context.user_data['form_data']) == len(context.user_data['fields']):
        await update.message.reply_text(
            "Great! All fields are filled. Generating your PDF...",
            reply_markup=ReplyKeyboardRemove(),
        )
        
        # Generate PDF
        form_data = context.user_data['form_data']
        template_name = context.user_data['template_name']
        template = context.user_data['template']
        
        # Create output directory if it doesn't exist
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        
        # Generate filename based on template name and timestamp
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_filename = f"filled_{template_name.replace(' ', '_')}_{timestamp}.pdf"
        output_path = os.path.join(OUTPUT_DIR, output_filename)
        
        # Generate the PDF
        pdf_success = generate_pdf(form_data, template, output_path)
        
        # Save data to Google Sheets
        sheets_success = await save_to_sheets(form_data, context.user_data['fields'])
        
        if pdf_success:
            # Send the PDF to the user
            try:
                await update.message.reply_document(
                    document=open(output_path, 'rb'),
                    filename=output_filename,
                    caption="Here's your filled PDF!"
                )
                
                if sheets_success:
                    await update.message.reply_text("Form data saved to Google Sheets.")
                else:
                    await update.message.reply_text("Note: Couldn't save to Google Sheets. Please check logs.")
            except Exception as e:
                logger.error(f"Error sending PDF: {e}")
                await update.message.reply_text(
                    "The PDF was generated, but I couldn't send it to you. Please check the logs."
                )
            finally:
                # Clear user data
                context.user_data.clear()
                return ConversationHandler.END
        else:
            await update.message.reply_text(
                "Sorry, there was an error generating your PDF."
            )
            # Clear user data
            context.user_data.clear()
            return ConversationHandler.END
    
    # If not all fields are filled, ask for the next one
    remaining_fields = [f for f in context.user_data['fields'] if f not in context.user_data['form_data']]
    reply_keyboard = [[field] for field in remaining_fields]
    
    await update.message.reply_text(
        f"Perfect! '{field}' set to '{text}'.\n\n"
        "What field would you like to fill next?",
        reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True),
    )
    
    return CHOOSING

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel and end the conversation."""
    context.user_data.clear()
    await update.message.reply_text(
        "Operation cancelled.", 
        reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END

def main() -> None:
    """Start the bot."""
    try:
        # Create the Application
        application = Application.builder().token(TELEGRAM_TOKEN).build()

        # Add conversation handler for PDF filling
        conv_handler = ConversationHandler(
            entry_points=[CommandHandler("fill", fill_start)],
            states={
                TEMPLATE_SELECTION: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND, 
                        template_selection
                    )
                ],
                CHOOSING: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND, 
                        regular_choice
                    )
                ],
                TYPING_REPLY: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND,
                        received_information,
                    )
                ],
            },
            fallbacks=[CommandHandler("cancel", cancel)],
        )

        application.add_handler(conv_handler)
        
        # Add basic command handlers
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("help", help_command))

        # Ensure required directories exist
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        
        logger.info(f"Starting bot. Output directory: {OUTPUT_DIR}")
        
        # Start the Bot
        application.run_polling()
    except Exception as e:
        logger.error(f"Fatal error: {e}")

if __name__ == '__main__':
    main()