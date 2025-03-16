#!/usr/bin/env python3
# AutoPDF Bot - A Telegram bot that fills PDF forms with user data

import os
import logging
from typing import Dict, List, Optional, Tuple
import json
import io
from datetime import datetime
from dotenv import load_dotenv
import tempfile
from telegram.constants import ParseMode

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

# Google Drive integration
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

# PDF processing
from pdfrw2 import PdfReader, PdfWriter, IndirectPdfDict

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# States for conversation handler
CHOOSING, TYPING_REPLY, TEMPLATE_SELECTION, CHOOSING_NEXT_ACTION = range(4)

# Configuration from environment
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
CREDENTIALS_FILE = os.environ.get('GOOGLE_CREDENTIALS_FILE', 'google_credentials.json')
OUTPUT_DIR = os.environ.get('OUTPUT_DIR', 'generated')

# Validate required configuration
if not TELEGRAM_TOKEN:
    raise ValueError("No TELEGRAM_TOKEN found in environment variables. Please set it in .env file.")

# Google API setup
SCOPES = [
    'https://www.googleapis.com/auth/drive'
]

def setup_google_services():
    """Set up Google Drive client with credentials"""
    try:
        if not os.path.exists(CREDENTIALS_FILE):
            logger.warning(f"Google credentials file not found: {CREDENTIALS_FILE}")
            return None
            
        creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=SCOPES)
        drive_service = build('drive', 'v3', credentials=creds)
        return drive_service
    except Exception as e:
        logger.error(f"Error setting up Google services: {e}")
        return None

def list_pdf_templates():
    """List all PDF forms in Google Drive"""
    try:
        drive_service = setup_google_services()
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
    """Download a PDF form from Google Drive"""
    try:
        drive_service = setup_google_services()
        if not drive_service:
            return None, None
            
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
    """Extract form fields from a PDF form"""
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
    Generate a PDF by filling a form with data
    
    Args:
        data: Dictionary with field names and values
        template: PdfReader object with the form
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

# Command handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a message when the command /start is issued."""
    user = update.effective_user
    await update.message.reply_text(
        f"Hi {user.first_name}! I'm AutoPDF Bot. I help you fill PDF forms automatically.\n\n"
        f"Use /fill to start filling a PDF form.\n"
        f"Use /help to see available commands."
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a message when the command /help is issued."""
    await update.message.reply_text(
        "Here's how to use this bot:\n\n"
        "/start - Start the bot\n"
        "/fill - Fill a PDF form\n"
        "/help - Show this help message\n"
        "/cancel - Cancel the current operation"
    )

# PDF filling conversation handlers
async def fill_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start the PDF filling process by offering form selection"""
    # Get available forms from Google Drive
    templates = list_pdf_templates()
    
    if not templates:
        await update.message.reply_text(
            "No PDF forms found in your Google Drive. Please upload at least one PDF form."
        )
        return ConversationHandler.END
    
    context.user_data['templates'] = templates
    
    # Create keyboard with form options
    reply_keyboard = [[template['name']] for template in templates]
    
    await update.message.reply_text(
        "Let's fill a PDF form. Please select a form:",
        reply_markup=ReplyKeyboardMarkup(
            reply_keyboard, one_time_keyboard=True
        ),
    )
    
    return TEMPLATE_SELECTION

async def template_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle form selection"""
    selected_template_name = update.message.text
    templates = context.user_data.get('templates', [])
    
    # Find the selected template
    selected_template = next((t for t in templates if t['name'] == selected_template_name), None)
    
    if not selected_template:
        await update.message.reply_text(
            "Sorry, I couldn't find that form. Please try again."
        )
        return ConversationHandler.END
    
    # Download form and extract form fields
    template_content, _ = download_template_from_drive(selected_template['id'])
    
    if not template_content:
        await update.message.reply_text(
            "Sorry, I couldn't download the form. Please check permissions and try again."
        )
        return ConversationHandler.END
    
    # Extract fields from form
    fields, template = extract_pdf_form_fields(template_content)
    
    if not fields:
        await update.message.reply_text(
            "No fillable fields found in this form. Please select a PDF with form fields."
        )
        return ConversationHandler.END
    
    # Save form details in user data
    context.user_data['form_data'] = {}
    context.user_data['template_id'] = selected_template['id']
    context.user_data['template_name'] = selected_template_name
    context.user_data['fields'] = fields
    context.user_data['template'] = template
    context.user_data['template_content'] = template_content
    
    # Create keyboard with field options
    reply_keyboard = [[field] for field in fields]
    
    await update.message.reply_text(
        f"Selected form: {selected_template_name}\n\n"
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
        
        # Generate filename based on form name and timestamp
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_filename = f"filled_{template_name.replace(' ', '_')}_{timestamp}.pdf"
        output_path = os.path.join(OUTPUT_DIR, output_filename)
        
        # Generate the PDF
        pdf_success = generate_pdf(form_data, template, output_path)
        
        if pdf_success:
            # Send the PDF to the user
            try:
                pdf_file = open(output_path, 'rb')
                await update.message.reply_document(
                    document=pdf_file,
                    filename=output_filename,
                    caption="Here's your filled PDF!"
                )
                pdf_file.close()
                
                # Save the path for potential re-sending
                context.user_data['last_pdf_path'] = output_path
                context.user_data['last_pdf_filename'] = output_filename
                
                # Offer options for what to do next
                reply_keyboard = [['Send Again'], ['New Form'], ['Exit']]
                await update.message.reply_text(
                    "What would you like to do next?",
                    reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True),
                )
                
                # Add completed message with form data summary
                summary = "*Form Data Summary:*\n"
                for field, value in form_data.items():
                    summary += f"*{field}:* {value}\n"
                
                await update.message.reply_text(
                    summary,
                    parse_mode=ParseMode.MARKDOWN,
                )
                
                return CHOOSING_NEXT_ACTION
            except Exception as e:
                logger.error(f"Error sending PDF: {e}")
                await update.message.reply_text(
                    "The PDF was generated, but I couldn't send it to you. Please try again."
                )
                # Provide a retry option
                reply_keyboard = [['Try Again'], ['New Form'], ['Exit']]
                await update.message.reply_text(
                    "What would you like to do?",
                    reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True),
                )
                return CHOOSING_NEXT_ACTION
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

async def handle_next_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle user's choice after completing a form."""
    choice = update.message.text
    
    if choice == "Send Again":
        # Resend the PDF
        try:
            pdf_path = context.user_data.get('last_pdf_path')
            filename = context.user_data.get('last_pdf_filename')
            
            if pdf_path and os.path.exists(pdf_path):
                pdf_file = open(pdf_path, 'rb')
                await update.message.reply_document(
                    document=pdf_file,
                    filename=filename,
                    caption="Here's your filled PDF again!"
                )
                pdf_file.close()
                
                # Ask again what to do next
                reply_keyboard = [['Send Again'], ['New Form'], ['Exit']]
                await update.message.reply_text(
                    "What would you like to do next?",
                    reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True),
                )
                return CHOOSING_NEXT_ACTION
            else:
                await update.message.reply_text(
                    "Sorry, I couldn't find the PDF file. Let's start over."
                )
                # Clear user data and start a new form
                context.user_data.clear()
                return await fill_start(update, context)
        except Exception as e:
            logger.error(f"Error resending PDF: {e}")
            await update.message.reply_text(
                "Sorry, I couldn't resend the PDF. Let's start over."
            )
            context.user_data.clear()
            return await fill_start(update, context)
    
    elif choice == "New Form":
        # Clear current form data and start over
        context.user_data.clear()
        return await fill_start(update, context)
    
    elif choice == "Exit":
        # End the conversation
        await update.message.reply_text(
            "Thank you for using the AutoPDF Bot. Goodbye!",
            reply_markup=ReplyKeyboardRemove(),
        )
        context.user_data.clear()
        return ConversationHandler.END
    
    # Default fallback
    await update.message.reply_text(
        "I didn't understand that. Let's start over.",
        reply_markup=ReplyKeyboardRemove(),
    )
    context.user_data.clear()
    return await fill_start(update, context)

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel and end the conversation."""
    context.user_data.clear()
    await update.message.reply_text(
        "Operation cancelled.", 
        reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END

async def test_pdf_fields(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Command to test PDF form fields detection"""
    try:
        # List available PDFs in Drive
        templates = list_pdf_templates()
        
        if not templates:
            await update.message.reply_text(
                "No PDF forms found in Google Drive. Please upload a PDF form first."
            )
            return

        # Create a keyboard with PDF options
        reply_keyboard = [[template['name']] for template in templates]
        
        # Store templates in context for later use
        context.user_data['test_templates'] = templates
        
        await update.message.reply_text(
            "Please select a PDF form to analyze:",
            reply_markup=ReplyKeyboardMarkup(
                reply_keyboard, 
                one_time_keyboard=True
            )
        )
        
        # Set up the next step
        context.user_data['expecting_pdf_selection'] = True
        
    except Exception as e:
        logger.error(f"Error in test_pdf_fields: {e}")
        await update.message.reply_text(
            "Sorry, something went wrong. Please try again later."
        )

async def analyze_selected_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Analyze the selected PDF form and show field information"""
    if not context.user_data.get('expecting_pdf_selection'):
        return

    try:
        selected_name = update.message.text
        templates = context.user_data.get('test_templates', [])
        
        # Find the selected template
        selected_template = next(
            (t for t in templates if t['name'] == selected_name), 
            None
        )
        
        if not selected_template:
            await update.message.reply_text(
                "Sorry, I couldn't find that PDF. Please try again with /testpdf"
            )
            return

        # Download the PDF
        await update.message.reply_text("Downloading PDF form...")
        
        file_content, _ = download_template_from_drive(selected_template['id'])
        
        if not file_content:
            await update.message.reply_text(
                "Sorry, I couldn't download the PDF. Please check permissions and try again."
            )
            return

        # Analyze the PDF
        await update.message.reply_text("Analyzing form fields...")
        
        try:
            pdf = PdfReader(file_content)
            fields_info = []
            
            # Iterate through pages
            for page_num, page in enumerate(pdf.pages, 1):
                annotations = page.get('/Annots')
                if annotations:
                    for annotation in annotations:
                        if annotation['/Subtype'] == '/Widget':
                            field_info = {
                                'name': annotation['/T'],
                                'type': 'Unknown',
                                'page': page_num
                            }
                            
                            # Determine field type
                            if annotation['/FT'] == '/Tx':
                                field_info['type'] = 'Text'
                            elif annotation['/FT'] == '/Btn':
                                if annotation.get('/AS') == '/Off':
                                    field_info['type'] = 'Checkbox'
                                else:
                                    field_info['type'] = 'Radio Button'
                            elif annotation['/FT'] == '/Ch':
                                field_info['type'] = 'Choice'
                            
                            fields_info.append(field_info)

            if fields_info:
                # Create a formatted message with field information
                message = f"📄 Analysis of '{selected_name}':\n\n"
                message += f"Found {len(fields_info)} form fields:\n\n"
                
                for i, field in enumerate(fields_info, 1):
                    message += (f"{i}. Field: '{field['name']}'\n"
                              f"   Type: {field['type']}\n"
                              f"   Page: {field['page']}\n\n")
                
                # Split message if too long
                if len(message) > 4000:
                    chunks = [message[i:i+4000] for i in range(0, len(message), 4000)]
                    for chunk in chunks:
                        await update.message.reply_text(chunk)
                else:
                    await update.message.reply_text(message)
                
                await update.message.reply_text(
                    "✅ Analysis complete! These are all the form fields I can detect and fill."
                )
            else:
                await update.message.reply_text(
                    "⚠️ No fillable form fields found in this PDF. "
                    "Make sure this is a PDF form with fillable fields."
                )
                
        except Exception as e:
            logger.error(f"Error analyzing PDF: {e}")
            await update.message.reply_text(
                "Sorry, I couldn't analyze this PDF. "
                "Make sure it's a valid PDF form with fillable fields."
            )
            
    except Exception as e:
        logger.error(f"Error in analyze_selected_pdf: {e}")
        await update.message.reply_text(
            "Sorry, something went wrong. Please try again with /testpdf"
        )
    finally:
        # Clear the expectation flag
        context.user_data['expecting_pdf_selection'] = False
        context.user_data.pop('test_templates', None)

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
                CHOOSING_NEXT_ACTION: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND,
                        handle_next_action,
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
        
        # Add the test command
        application.add_handler(CommandHandler("testpdf", test_pdf_fields))
        application.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND & 
            filters.CREATE_FILTER(
                lambda _, ctx: ctx.user_data.get('expecting_pdf_selection')
            ),
            analyze_selected_pdf
        ))

        # Start the Bot
        application.run_polling()
    except Exception as e:
        logger.error(f"Fatal error: {e}")

if __name__ == '__main__':
    main()