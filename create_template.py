#!/usr/bin/env python3
"""
Template Creator for AutoPDF Bot

This script creates a simple fillable PDF template that can be used with AutoPDF Bot.
It requires the reportlab and pdfrw2 libraries.

Usage:
    python create_template.py
"""

import os
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib import colors
from pdfrw2 import PdfReader, PdfWriter, IndirectPdfDict
import pdfrw2.buildxobj

# Directory for templates
TEMPLATE_DIR = 'templates'
os.makedirs(TEMPLATE_DIR, exist_ok=True)

# Temporary file for the base PDF
TMP_FILE = os.path.join(TEMPLATE_DIR, 'tmp_invoice.pdf')
OUTPUT_FILE = os.path.join(TEMPLATE_DIR, 'invoice_template.pdf')

def create_base_pdf():
    """Create a basic invoice layout with reportlab"""
    c = canvas.Canvas(TMP_FILE, pagesize=letter)
    width, height = letter
    
    # Add a title
    c.setFont("Helvetica-Bold", 24)
    c.drawCentredString(width/2, height - 1*inch, "INVOICE")
    
    # Add company details
    c.setFont("Helvetica-Bold", 12)
    c.drawString(1*inch, height - 2*inch, "From:")
    c.setFont("Helvetica", 12)
    c.drawString(1*inch, height - 2.2*inch, "Your Company Name")
    c.drawString(1*inch, height - 2.4*inch, "Your Address")
    c.drawString(1*inch, height - 2.6*inch, "Your City, State ZIP")
    c.drawString(1*inch, height - 2.8*inch, "Phone: (555) 555-5555")
    
    # Client section
    c.setFont("Helvetica-Bold", 12)
    c.drawString(1*inch, height - 3.5*inch, "Bill To:")
    
    # Draw boxes for client fields
    c.rect(1*inch, height - 4.8*inch, 3*inch, 1.1*inch)
    
    # Invoice details section
    c.setFont("Helvetica-Bold", 12)
    c.drawString(5*inch, height - 3.5*inch, "Invoice Details:")
    
    # Draw boxes for invoice details
    c.rect(5*inch, height - 5.1*inch, 2.5*inch, 1.4*inch)
    
    # Description section
    c.setFont("Helvetica-Bold", 12)
    c.drawString(1*inch, height - 5.5*inch, "Description:")
    
    # Draw box for description
    c.rect(1*inch, height - 7*inch, 6.5*inch, 1*inch)
    
    # Amount section
    c.setFont("Helvetica-Bold", 12)
    c.drawString(5*inch, height - 7.5*inch, "Amount:")
    
    # Draw box for amount
    c.rect(6*inch, height - 7.8*inch, 1.5*inch, 0.3*inch)
    
    # Add footer
    c.setFont("Helvetica", 8)
    c.drawCentredString(width/2, 0.5*inch, "Generated with AutoPDF Bot")
    
    c.save()
    
    return TMP_FILE

def add_form_fields(input_pdf, output_pdf):
    """Add form fields to the PDF template"""
    template = PdfReader(input_pdf)
    
    # Add form fields for the client information
    fields = [
        # Client info
        {
            'name': 'client_name',
            'rect': (72, 468, 288, 486),  # 1 inch = 72 points
            'value': 'Client Name'
        },
        {
            'name': 'client_email',
            'rect': (72, 450, 288, 468),
            'value': 'client@example.com'
        },
        # Invoice details
        {
            'name': 'invoice_number',
            'rect': (360, 468, 540, 486),
            'value': 'INV-001'
        },
        {
            'name': 'invoice_date',
            'rect': (360, 450, 540, 468),
            'value': '2023-01-01'
        },
        {
            'name': 'due_date',
            'rect': (360, 432, 540, 450),
            'value': '2023-01-31'
        },
        # Description
        {
            'name': 'description',
            'rect': (72, 360, 540, 432),
            'value': 'Services rendered'
        },
        # Amount
        {
            'name': 'amount',
            'rect': (432, 288, 540, 306),
            'value': '$100.00'
        }
    ]
    
    # Create annotations with form fields
    for page in template.pages:
        annotations = []
        for field in fields:
            annotation = IndirectPdfDict(
                Type=pdfrw2.objects.names_pdfrw.Annot,
                Subtype=pdfrw2.objects.names_pdfrw.Widget,
                FT=pdfrw2.objects.names_pdfrw.Tx,
                Rect=field['rect'],
                T=field['name'],
                V=field['value'],
                AP=''
            )
            annotations.append(annotation)
        
        if page.Annots:
            page.Annots.extend(annotations)
        else:
            page.Annots = annotations
    
    # Write the output file
    PdfWriter().write(output_pdf, template)

def main():
    """Create a fillable PDF invoice template"""
    print("Creating invoice template...")
    
    # Create the base PDF
    base_pdf = create_base_pdf()
    
    # Add form fields
    add_form_fields(base_pdf, OUTPUT_FILE)
    
    # Clean up temporary files
    if os.path.exists(TMP_FILE):
        os.remove(TMP_FILE)
    
    print(f"Template created successfully: {OUTPUT_FILE}")
    print("You can now use this template with your AutoPDF Bot.")
    print("Make sure to configure your .env file to point to this template.")

if __name__ == '__main__':
    main() 