#!/usr/bin/env python3
# AutoPDF Bot - A Telegram bot that fills PDF forms with user data

import os
import logging
from typing import Dict, List, Optional, Tuple
import json
import io
from datetime import datetime, timedelta
from dotenv import load_dotenv
import tempfile
from telegram.constants import ParseMode

# Force reload of environment variables
os.environ.clear()
load_dotenv(override=True)

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
from PyPDF2 import PdfReader, PdfWriter

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Define conversation states
SELECTING_TEMPLATE = 0
CHOOSING_FIELD_NAMES = 1
CUSTOMIZING_FIELDS = 2
CHOOSING_FILL_METHOD = 3
BULK_ENTRY = 4
CHOOSING = 5
TYPING_REPLY = 6
CHOOSING_NEXT_ACTION = 7

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

# Field name mapping for better display names
FIELD_MAPPING = {
    # Default mappings for common form fields
    'f1': 'Full Name',
    'f2': 'Email',
    'f3': 'Phone Number',
    'f4': 'Address',
    'f5': 'City',
    'f6': 'State',
    'f7': 'Zip Code',
    'Text1': 'Name',
    'Text2': 'Email',
    'Text3': 'Phone',
    'Text4': 'Address',
    'Text5': 'City',
    'Text6': 'State',
    'Text7': 'Zip',
    'name': 'Full Name',
    'email': 'Email Address',
    'phone': 'Phone Number',
    'address': 'Street Address',
    'city': 'City',
    'state': 'State/Province',
    'zip': 'Postal Code',
    'dob': 'Date of Birth',
    'date': 'Date',
    'signature': 'Signature',
    'comments': 'Comments',
    'notes': 'Notes',
    'amount': 'Amount',
    'price': 'Price',
    'quantity': 'Quantity',
    'total': 'Total',
    'company': 'Company Name',
    'title': 'Job Title',
    # Add more mappings as needed
}

# Template-specific field mappings
# Structure: {'template_id': {'internal_field_name': 'User Friendly Name'}}
TEMPLATE_FIELD_MAPPINGS = {
    # Example for a specific template (replace with your actual template IDs)
    'template_id_1': {
        'topmostSubform[0].Page1[0].f1_1[0]': 'Full Name',
        'topmostSubform[0].Page1[0].f1_2[0]': 'Email Address',
        'topmostSubform[0].Page1[0].f1_3[0]': 'Phone Number',
        # Add more field mappings for this template
    },
    # Add more templates as needed
    'template_id_2': {
        'field_1': 'Customer Name',
        'field_2': 'Order Number',
        'field_3': 'Delivery Address',
        # Add more field mappings for this template
    },
    # You can add mappings for any number of templates here
}

def get_display_name(field_name, template_id=None):
    """Convert internal field names to user-friendly display names
    
    Args:
        field_name: The internal field name from the PDF
        template_id: Optional template ID to use template-specific mappings
        
    Returns:
        A user-friendly display name for the field
    """
    # First check template-specific mappings if template_id is provided
    if template_id and template_id in TEMPLATE_FIELD_MAPPINGS:
        template_mappings = TEMPLATE_FIELD_MAPPINGS[template_id]
        if field_name in template_mappings:
            return template_mappings[field_name]
    
    # Fall back to default mappings if no template-specific mapping exists
    if field_name in FIELD_MAPPING:
        return FIELD_MAPPING[field_name]
    
    # Try to make the field name more readable if no mapping exists
    # Convert camelCase or snake_case to Title Case with spaces
    display_name = field_name
    
    # Replace underscores with spaces
    display_name = display_name.replace('_', ' ')
    
    # Insert space before capitals in camelCase
    display_name = ''.join([' ' + c if c.isupper() else c for c in display_name]).strip()
    
    # Title case the result
    display_name = display_name.title()
    
    return display_name

def create_custom_field_mapping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Create or update custom field mappings for the current form"""
    fields = context.user_data.get('fields', [])
    template_id = context.user_data.get('template_id')
    custom_mappings = {}
    
    for field in fields:
        # Use template-specific mapping if available, otherwise use default
        display_name = get_display_name(field, template_id)
        custom_mappings[field] = display_name
    
    # Store the custom mappings in user data
    context.user_data['field_mappings'] = custom_mappings
    
    return custom_mappings

async def customize_field_names(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Allow the user to customize field names"""
    fields = context.user_data.get('fields', [])
    
    # Create a mapping first
    mappings = create_custom_field_mapping(update, context)
    
    # Create a message template for customization
    message = "Current field names:\n\n"
    for field, display_name in mappings.items():
        message += f"{field} → {display_name}\n"
    
    message += "\nTo customize field names, reply with the changes in this format:\n"
    message += "field_name1: New Display Name 1\nfield_name2: New Display Name 2\n"
    message += "\nOr type 'skip' to keep current names."
    
    await update.message.reply_text(message)
    
    # Set state for collecting custom field names
    context.user_data['awaiting_field_names'] = True
    
    return CUSTOMIZING_FIELDS

async def process_field_customization(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Process the user's custom field name mappings"""
    text = update.message.text
    
    if text.lower() == 'skip':
        # Skip customization and move to filling method choice
        fields = context.user_data['fields']
        reply_keyboard = [["Fill Fields One-by-One"], ["Fill All Fields at Once"]]
        
        await update.message.reply_text(
            f"Using default field names. How would you like to fill this form?",
            reply_markup=ReplyKeyboardMarkup(
                reply_keyboard, one_time_keyboard=True
            ),
        )
        return CHOOSING_FILL_METHOD
    
    # Parse the custom mappings
    lines = text.strip().split('\n')
    custom_mappings = context.user_data.get('field_mappings', {}).copy()
    
    updated = False
    for line in lines:
        if ':' in line:
            field, new_name = line.split(':', 1)
            field = field.strip()
            new_name = new_name.strip()
            
            if field in custom_mappings:
                custom_mappings[field] = new_name
                updated = True
    
    if updated:
        # Update the mappings
        context.user_data['field_mappings'] = custom_mappings
        
        message = "Field names updated! New mappings:\n\n"
        for field, display_name in custom_mappings.items():
            message += f"{field} → {display_name}\n"
        
        await update.message.reply_text(message)
    else:
        await update.message.reply_text(
            "No valid mappings found. Please use the format 'field_name: New Display Name' or type 'skip'."
        )
        return CUSTOMIZING_FIELDS
    
    # Now move to filling method choice
    reply_keyboard = [["Fill Fields One-by-One"], ["Fill All Fields at Once"]]
    
    await update.message.reply_text(
        f"How would you like to fill this form?",
        reply_markup=ReplyKeyboardMarkup(
            reply_keyboard, one_time_keyboard=True
        ),
    )
    return CHOOSING_FILL_METHOD

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
        return file_content
    except Exception as e:
        logger.error(f"Error downloading template: {e}")
        return None

def extract_form_fields(template_content):
    """Extract form fields from a PDF template"""
    try:
        # Create a temporary file for the template
        with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as temp_file:
            temp_file.write(template_content.getvalue())
            temp_path = temp_file.name
        
        # Read the template using PyPDF2
        template_pdf = PdfReader(temp_path)
        
        # Extract fields
        fields = []
        form_fields = template_pdf.get_fields()
        
        if form_fields:
            # Add all field names to our list
            fields = list(form_fields.keys())
            logger.info(f"Found {len(fields)} form fields in the PDF")
        else:
            logger.warning("No form fields found in the PDF")
        
        # Remove the temporary file
        os.remove(temp_path)
        
        return fields
    except Exception as e:
        logger.error(f"Error extracting form fields: {e}")
        return []

def generate_pdf(form_data, template_content, output_path):
    """Generate filled PDF from template and form data"""
    try:
        # Create a temporary file for the template
        with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as temp_file:
            temp_file.write(template_content.getvalue())
            temp_path = temp_file.name

        # Read the template using PyPDF2
        template_pdf = PdfReader(temp_path)
        
        # Create a PDF writer
        writer = PdfWriter()
        
        # Add all pages from the template
        for page_num in range(len(template_pdf.pages)):
            writer.add_page(template_pdf.pages[page_num])
        
        # Update form fields with data
        # In PyPDF2 v3.x, update_page_form_field_values takes the pages to update
        # and the fields dictionary
        writer.update_page_form_field_values(writer.pages, form_data)
        
        # Set the "need appearances" flag to ensure form fields are visible
        try:
            writer._root_object['/AcroForm'].update({
                '/NeedAppearances': True
            })
        except Exception as e:
            logger.warning(f"Could not set NeedAppearances flag: {e}")
        
        # Write the filled PDF
        with open(output_path, "wb") as output_file:
            writer.write(output_file)
        
        # Remove the temporary file
        os.remove(temp_path)
        
        logger.info(f"Successfully generated PDF at {output_path}")
        return True
    except Exception as e:
        logger.error(f"Error generating PDF: {e}")
        return False

class PDFStorage:
    def __init__(self, storage_dir='user_pdfs'):
        self.storage_dir = storage_dir
        self.index_file = os.path.join(storage_dir, 'pdf_index.json')
        os.makedirs(storage_dir, exist_ok=True)
        self.load_index()

    def load_index(self):
        """Load the PDF index from file"""
        try:
            if os.path.exists(self.index_file):
                with open(self.index_file, 'r') as f:
                    self.index = json.load(f)
            else:
                self.index = {}
        except Exception as e:
            logger.error(f"Error loading PDF index: {e}")
            self.index = {}

    def save_index(self):
        """Save the PDF index to file"""
        try:
            with open(self.index_file, 'w') as f:
                json.dump(self.index, f)
        except Exception as e:
            logger.error(f"Error saving PDF index: {e}")

    def store_pdf(self, user_id: int, pdf_path: str, filename: str):
        """Store PDF information for a user"""
        if str(user_id) not in self.index:
            self.index[str(user_id)] = []

        # Add new PDF info
        pdf_info = {
            'path': pdf_path,
            'filename': filename,
            'timestamp': datetime.now().isoformat(),
            'expires_at': (datetime.now() + timedelta(days=7)).isoformat()  # Keep PDFs for 7 days
        }
        
        self.index[str(user_id)].append(pdf_info)
        self.save_index()

    def get_user_pdfs(self, user_id: int):
        """Get all PDFs for a user"""
        return self.index.get(str(user_id), [])

    def cleanup_old_pdfs(self):
        """Remove expired PDFs"""
        now = datetime.now()
        for user_id in list(self.index.keys()):
            pdfs = self.index[user_id]
            valid_pdfs = []
            
            for pdf in pdfs:
                expires_at = datetime.fromisoformat(pdf['expires_at'])
                if expires_at > now:
                    valid_pdfs.append(pdf)
                else:
                    # Remove the actual PDF file
                    try:
                        if os.path.exists(pdf['path']):
                            os.remove(pdf['path'])
                    except Exception as e:
                        logger.error(f"Error removing old PDF: {e}")

            if valid_pdfs:
                self.index[user_id] = valid_pdfs
            else:
                del self.index[user_id]
        
        self.save_index()

# Initialize PDF storage
pdf_storage = PDFStorage()

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
        "/form - Fill a PDF form\n"
        "/fields - View field names of a PDF form (for developers)\n"
        "/help - Show this help message\n"
        "/cancel - Cancel the current operation\n\n"
        "To customize field names for your forms, edit the TEMPLATE_FIELD_MAPPINGS in the code."
    )

# PDF filling conversation handlers
async def form(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
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
    
    return SELECTING_TEMPLATE

async def template_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle template selection and extract fields"""
    template_name = update.message.text
    
    # Check if the selected template exists in our data
    if 'templates' not in context.user_data or template_name not in [t['name'] for t in context.user_data['templates']]:
        await update.message.reply_text(
            "Sorry, I couldn't find that template. Please select a template from the list.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return ConversationHandler.END
    
    # Get the template ID
    template_id = None
    for template in context.user_data['templates']:
        if template['name'] == template_name:
            template_id = template['id']
            break
    
    if not template_id:
        await update.message.reply_text(
            "Sorry, I couldn't find the ID for that template. Please try again.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return ConversationHandler.END
    
    # Download the template and extract fields
    await update.message.reply_text(
        f"Downloading template: {template_name}...",
        reply_markup=ReplyKeyboardRemove(),
    )
    
    try:
        # Download the PDF template
        template_content = download_template_from_drive(template_id)
        if not template_content:
            await update.message.reply_text(
                "Sorry, I couldn't download that template. Please try again or choose a different template.",
                reply_markup=ReplyKeyboardRemove(),
            )
            return ConversationHandler.END
        
        # Extract form fields
        fields = extract_form_fields(template_content)
        if not fields:
            await update.message.reply_text(
                "This PDF doesn't appear to have any fillable fields. Please choose a fillable PDF template.",
                reply_markup=ReplyKeyboardRemove(),
            )
            return ConversationHandler.END
        
        # Save form details in user_data
        context.user_data['template_id'] = template_id
        context.user_data['template_name'] = template_name
        context.user_data['fields'] = fields
        context.user_data['template'] = template_content
        
        # Check if we have template-specific mappings for this template
        has_template_mappings = template_id in TEMPLATE_FIELD_MAPPINGS
        
        # Create field mappings (will use template-specific mappings if available)
        create_custom_field_mapping(update, context)
        
        # If we have template-specific mappings, skip the customization step
        if has_template_mappings:
            field_mappings = context.user_data.get('field_mappings', {})
            
            # Show the mappings that will be used
            message = f"Using predefined field mappings for this template:\n\n"
            for field, display_name in field_mappings.items():
                message += f"{field} → {display_name}\n"
            
            await update.message.reply_text(message)
            
            # Go directly to filling method choice
            reply_keyboard = [["Fill Fields One-by-One"], ["Fill All Fields at Once"]]
            await update.message.reply_text(
                f"How would you like to fill this form?",
                reply_markup=ReplyKeyboardMarkup(
                    reply_keyboard, one_time_keyboard=True
                ),
            )
            return CHOOSING_FILL_METHOD
        else:
            # Ask if user wants to customize field names
            reply_keyboard = [['Customize Field Names'], ['Use Default Names']]
            await update.message.reply_text(
                f"I found {len(fields)} fillable fields in this form.\n\n"
                "Would you like to customize the field names or use the default names?",
                reply_markup=ReplyKeyboardMarkup(
                    reply_keyboard, one_time_keyboard=True, input_field_placeholder="Choose an option"
                ),
            )
            return CHOOSING_FIELD_NAMES
        
    except Exception as e:
        logger.error(f"Error processing template: {e}")
        await update.message.reply_text(
            "Sorry, there was an error processing your template. Please try again.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return ConversationHandler.END

async def choose_field_naming(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle the user's choice for field naming"""
    choice = update.message.text
    
    if choice == "Customize Field Names":
        # Go to field name customization
        return await customize_field_names(update, context)
    else:
        # Skip to filling method choice
        fields = context.user_data['fields']
        # Create default mappings
        create_custom_field_mapping(update, context)
        
        reply_keyboard = [["Fill Fields One-by-One"], ["Fill All Fields at Once"]]
        
        await update.message.reply_text(
            f"Using default field names. How would you like to fill this form?",
            reply_markup=ReplyKeyboardMarkup(
                reply_keyboard, one_time_keyboard=True
            ),
        )
        return CHOOSING_FILL_METHOD

async def choose_fill_method(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle the user's choice of fill method"""
    text = update.message.text
    
    if text == "Fill Fields One-by-One":
        # Create keyboard with field options for individual filling
        fields = context.user_data['fields']
        field_mappings = context.user_data.get('field_mappings', {})
        
        # Create a keyboard with display names
        reply_keyboard = []
        for field in fields:
            display_name = field_mappings.get(field, get_display_name(field))
            reply_keyboard.append([display_name])
        
        await update.message.reply_text(
            "Please choose a field to fill:",
            reply_markup=ReplyKeyboardMarkup(
                reply_keyboard, one_time_keyboard=True
            ),
        )
        return CHOOSING
        
    elif text == "Fill All Fields at Once":
        # Provide a template for bulk filling
        fields = context.user_data['fields']
        field_mappings = context.user_data.get('field_mappings', {})
        
        # Create a template for the user to fill
        template_text = "Please fill in values for all fields below:\n\n"
        
        # Add each field to the template with a clear format
        for field in fields:
            # Use the custom mapping or default display name
            display_name = field_mappings.get(field, get_display_name(field))
            template_text += f"{display_name}: [Enter value here]\n"
            
        template_text += "\nReplace '[Enter value here]' with your actual values, keeping the field names intact."
        
        await update.message.reply_text(
            template_text,
            reply_markup=ReplyKeyboardRemove(),
        )
        
        return BULK_ENTRY

async def regular_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Ask the user for info about the selected field."""
    display_name = update.message.text
    fields = context.user_data['fields']
    field_mappings = context.user_data.get('field_mappings', {})
    
    # Find the actual field name from the display name
    field_name = None
    for field in fields:
        if field_mappings.get(field, get_display_name(field)) == display_name:
            field_name = field
            break
    
    if not field_name:
        await update.message.reply_text(
            f"Could not find field for '{display_name}'. Please try again.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return ConversationHandler.END
    
    # Store the actual field name in context
    context.user_data['choice'] = field_name
    
    await update.message.reply_text(
        f"Please enter the value for field '{display_name}':",
        reply_markup=ReplyKeyboardRemove(),
    )
    
    return TYPING_REPLY

async def process_bulk_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Process the bulk input from the user"""
    raw_text = update.message.text
    fields = context.user_data['fields']
    field_mappings = context.user_data.get('field_mappings', {})
    
    # Initialize data dictionary
    form_data = {}
    
    # Parse the input line by line
    lines = raw_text.strip().split('\n')
    
    # Track which fields were filled
    filled_fields = []
    missing_fields = []
    
    for field in fields:
        # Get the display name used in the template
        display_name = field_mappings.get(field, get_display_name(field))
        
        # Look for the field in the input
        found = False
        for line in lines:
            if line.startswith(f"{display_name}:"):
                # Extract the value after the colon
                value = line[len(display_name)+1:].strip()
                
                # Ignore placeholder text
                if value and value != "[Enter value here]":
                    form_data[field] = value
                    filled_fields.append(field)
                    found = True
                    break
        
        if not found:
            missing_fields.append(display_name)
    
    if missing_fields:
        # Some fields are missing
        missing_text = "\n".join(missing_fields)
        await update.message.reply_text(
            f"The following fields are missing or have no value:\n\n{missing_text}\n\n"
            f"Please provide values for all fields.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return BULK_ENTRY
    
    # Save the form data
    context.user_data['form_data'] = form_data
    
    # Generate the PDF
    await update.message.reply_text(
        "Thanks! Generating your PDF with the provided values...",
        reply_markup=ReplyKeyboardRemove(),
    )
    
    # Use the same PDF generation logic as in received_information
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
            with open(output_path, 'rb') as pdf_file:
                await update.message.reply_document(
                    document=pdf_file,
                    filename=output_filename,
                    caption="Here's your filled PDF!"
                )
                
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
                display_name = field_mappings.get(field, get_display_name(field))
                summary += f"*{display_name}:* {value}\n"
            
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

async def received_information(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Store user info and ask for the next field."""
    text = update.message.text
    field = context.user_data['choice']
    
    # Initialize form_data if not exists
    if 'form_data' not in context.user_data:
        context.user_data['form_data'] = {}
    
    # Store the entered value
    context.user_data['form_data'][field] = text
    
    # Get field mappings for better display
    field_mappings = context.user_data.get('field_mappings', {})
    
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
                with open(output_path, 'rb') as pdf_file:
                    await update.message.reply_document(
                        document=pdf_file,
                        filename=output_filename,
                        caption="Here's your filled PDF!"
                    )
                    
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
                    display_name = field_mappings.get(field, get_display_name(field))
                    summary += f"*{display_name}:* {value}\n"
                
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
    reply_keyboard = []
    for field in remaining_fields:
        display_name = field_mappings.get(field, get_display_name(field))
        reply_keyboard.append([display_name])
    
    # Get display name for the field that was just filled
    display_name = field_mappings.get(field, get_display_name(field))
    
    await update.message.reply_text(
        f"Perfect! '{display_name}' set to '{text}'.\n\n"
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
                with open(pdf_path, 'rb') as pdf_file:
                    await update.message.reply_document(
                        document=pdf_file,
                        filename=filename,
                        caption="Here's your filled PDF again!"
                    )
                
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
                return await form(update, context)
        except Exception as e:
            logger.error(f"Error resending PDF: {e}")
            await update.message.reply_text(
                "Sorry, I couldn't resend the PDF. Let's start over."
            )
            context.user_data.clear()
            return await form(update, context)
    
    elif choice == "New Form":
        # Clear current form data and start over
        context.user_data.clear()
        return await form(update, context)
    
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
    return await form(update, context)

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel and end the conversation."""
    context.user_data.clear()
    await update.message.reply_text(
        "Operation cancelled.", 
        reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END

async def view_field_names(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """View the field names of a PDF template to help with creating mappings"""
    # Get available forms from Google Drive
    templates = list_pdf_templates()
    
    if not templates:
        await update.message.reply_text(
            "No PDF forms found in your Google Drive. Please upload at least one PDF form."
        )
        return
    
    # Create keyboard with form options
    reply_keyboard = [[template['name']] for template in templates]
    
    await update.message.reply_text(
        "Select a form to view its field names:",
        reply_markup=ReplyKeyboardMarkup(
            reply_keyboard, one_time_keyboard=True
        ),
    )
    
    # Set up a one-time handler for the response
    context.user_data['awaiting_template_for_fields'] = True
    
    # Register a one-time handler
    application = context.application
    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND & filters.User(update.effective_user.id),
            view_template_fields,
            one_time=True
        )
    )

async def view_template_fields(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show the field names of the selected template"""
    template_name = update.message.text
    
    # Get available forms from Google Drive
    templates = list_pdf_templates()
    
    # Find the selected template
    template_id = None
    for template in templates:
        if template['name'] == template_name:
            template_id = template['id']
            break
    
    if not template_id:
        await update.message.reply_text(
            "Sorry, I couldn't find that template. Please try again."
        )
        return
    
    # Download the template
    await update.message.reply_text(f"Downloading template: {template_name}...")
    template_content = download_template_from_drive(template_id)
    
    if not template_content:
        await update.message.reply_text(
            "Sorry, I couldn't download that template. Please try again."
        )
        return
    
    # Extract fields
    fields = extract_form_fields(template_content)
    
    if not fields:
        await update.message.reply_text(
            "This PDF doesn't appear to have any fillable fields."
        )
        return
    
    # Show the fields
    message = f"Fields in template '{template_name}' (ID: {template_id}):\n\n"
    
    # Check if we have template-specific mappings
    has_mappings = template_id in TEMPLATE_FIELD_MAPPINGS
    
    for field in fields:
        if has_mappings and field in TEMPLATE_FIELD_MAPPINGS[template_id]:
            display_name = TEMPLATE_FIELD_MAPPINGS[template_id][field]
            message += f"{field} → {display_name}\n"
        else:
            message += f"{field}\n"
    
    # Add instructions for adding mappings
    message += "\n\nTo add these mappings to your code, add the following to TEMPLATE_FIELD_MAPPINGS:\n\n"
    message += f"'{template_id}': {{\n"
    for field in fields:
        # Suggest a default display name
        suggested_name = get_display_name(field)
        message += f"    '{field}': '{suggested_name}',\n"
    message += "},"
    
    await update.message.reply_text(message)

def main() -> None:
    """Run the bot."""
    # Create the Application
    application = Application.builder().token(os.getenv("TELEGRAM_TOKEN")).build()

    # Add conversation handler with the states
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            CommandHandler("form", form),
        ],
        states={
            SELECTING_TEMPLATE: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    template_selection,
                )
            ],
            CHOOSING_FIELD_NAMES: [
                MessageHandler(
                    filters.Regex("^(Customize Field Names|Use Default Names)$"),
                    choose_field_naming,
                )
            ],
            CUSTOMIZING_FIELDS: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    process_field_customization,
                )
            ],
            CHOOSING_FILL_METHOD: [
                MessageHandler(
                    filters.Regex("^(Fill Fields One-by-One|Fill All Fields at Once)$"),
                    choose_fill_method,
                )
            ],
            BULK_ENTRY: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    process_bulk_input,
                )
            ],
            CHOOSING: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    regular_choice,
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
                    filters.Regex("^(Send Again|New Form|Exit)$"),
                    handle_next_action,
                )
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    application.add_handler(conv_handler)

    # Help command
    application.add_handler(CommandHandler("help", help_command))
    
    # Field names command
    application.add_handler(CommandHandler("fields", view_field_names))

    # Start the Bot
    application.run_polling()

if __name__ == "__main__":
    main()