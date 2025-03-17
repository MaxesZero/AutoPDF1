#!/usr/bin/env python3
"""Test PyPDF2 for form extraction and filling"""

import os
import tempfile
import logging
from PyPDF2 import PdfReader, PdfWriter

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def extract_form_fields(pdf_path):
    """Extract form fields from a PDF file"""
    try:
        reader = PdfReader(pdf_path)
        fields = reader.get_fields()
        
        if fields:
            logger.info(f"Found {len(fields)} fields in the PDF form:")
            for field_name in fields:
                logger.info(f"  - {field_name}")
            return list(fields.keys())
        else:
            logger.warning("No form fields found in the PDF.")
            return []
    except Exception as e:
        logger.error(f"Error extracting form fields: {e}")
        return []

def fill_pdf_form(input_pdf, output_pdf, data):
    """Fill a PDF form with the provided data"""
    try:
        # Read the input PDF
        reader = PdfReader(input_pdf)
        
        # Create a PDF writer
        writer = PdfWriter()
        
        # Add all pages from the input PDF
        for page in range(len(reader.pages)):
            writer.add_page(reader.pages[page])
        
        # Update form fields with data
        writer.update_page_form_field_values(writer.pages, data)
        
        # Write the filled PDF
        with open(output_pdf, "wb") as output_file:
            writer.write(output_file)
            
        logger.info(f"Successfully filled form and saved to {output_pdf}")
        return True
    except Exception as e:
        logger.error(f"Error filling PDF form: {e}")
        return False

def main():
    """Main function to test PyPDF2"""
    # Ask for the path to a PDF form
    pdf_path = input("Enter the path to a PDF form: ")
    
    if not os.path.exists(pdf_path):
        logger.error(f"File not found: {pdf_path}")
        return
    
    # Extract and display form fields
    fields = extract_form_fields(pdf_path)
    
    if not fields:
        logger.error("No fields found or error occurred. Exiting.")
        return
    
    # Collect values for each field
    form_data = {}
    for field in fields:
        value = input(f"Enter value for '{field}': ")
        form_data[field] = value
    
    # Generate output filename
    base_name = os.path.basename(pdf_path)
    name, ext = os.path.splitext(base_name)
    output_pdf = f"{name}_filled{ext}"
    
    # Fill the form
    success = fill_pdf_form(pdf_path, output_pdf, form_data)
    
    if success:
        logger.info(f"Form filled successfully! Output file: {output_pdf}")
    else:
        logger.error("Failed to fill the form.")

if __name__ == "__main__":
    main() 