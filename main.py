#!/usr/bin/env python3
"""
Comic Compiler - A script to download comic pages and convert them to PDF and EPUB formats.

This script scrapes comic pages from grabber.zone, downloads images at full resolution,
and converts them into both PDF and EPUB formats.

Usage:
    python main.py <base_url> <end_number> <output_dir>

Example:
    python main.py "https://grabber.zone/comics/sonic-idw/sonic-the-hedgehog-01/" 10 "./output"
"""

import os
import sys
import re
import argparse
from pathlib import Path
from urllib.parse import urljoin, urlparse
import time
import requests
from bs4 import BeautifulSoup
from PIL import Image
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Image as RLImage, PageBreak
from reportlab.lib.utils import ImageReader
from ebooklib import epub
import base64
from io import BytesIO
from rich.console import Console
from rich.progress import Progress, TaskID, track
from rich.panel import Panel
from rich.text import Text
from rich import print as rprint

console = Console()

class ComicCompiler:
    def __init__(self, output_dir: str):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        })
    
    def extract_comic_title(self, url: str) -> str:
        """Extract comic title from the chapters_selectbox_holder or page title."""
        try:
            response = self.session.get(url)
            response.raise_for_status()
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Try to find the title in chapters_selectbox_holder
            selectbox = soup.find(class_='chapters_selectbox_holder')
            if selectbox:
                # Look for selected option or first option
                selected = selectbox.find('option', {'selected': True})
                if selected:
                    return selected.get_text().strip()
                first_option = selectbox.find('option')
                if first_option:
                    return first_option.get_text().strip()
            
            # Fallback to page title or h1
            title_tag = soup.find('h1') or soup.find('title')
            if title_tag:
                title = title_tag.get_text().strip()
                # Clean up the title
                title = re.sub(r'\s+', ' ', title)
                return title
                
            # Last resort - extract from URL
            path_parts = urlparse(url).path.strip('/').split('/')
            if path_parts:
                return path_parts[-1].replace('-', ' ').title()
                
        except Exception as e:
            console.print(f"[yellow]Warning: Could not extract title from {url}: {e}[/yellow]")
            
        return "Unknown Comic"
    
    def get_comic_images(self, url: str) -> tuple[str, list[str]]:
        """Extract all images from the reading-content div and return title and image URLs."""
        try:
            console.print(f"[blue]Fetching page: {url}[/blue]")
            response = self.session.get(url)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Extract title
            title = self.extract_comic_title(url)
            
            # Find the reading-content div
            reading_content = soup.find('div', class_='reading-content')
            if not reading_content:
                console.print(f"[red]No reading-content div found on {url}[/red]")
                return title, []
            
            # Find all images in the reading content
            images = reading_content.find_all('img')
            image_urls = []
            
            for img in images:
                # Get the src attribute
                src = img.get('src') or img.get('data-src') or img.get('data-lazy-src')
                if src:
                    # Convert relative URLs to absolute
                    full_url = urljoin(url, src)
                    image_urls.append(full_url)
            
            console.print(f"[green]Found {len(image_urls)} images on {url}[/green]")
            return title, image_urls
            
        except Exception as e:
            console.print(f"[red]Error fetching {url}: {e}[/red]")
            return "Unknown Comic", []
    
    def download_image(self, url: str, filepath: Path, max_retries: int = 3) -> bool:
        """Download an image from URL to filepath with retry logic."""
        for attempt in range(max_retries):
            try:
                response = self.session.get(url, timeout=30)
                response.raise_for_status()
                
                with open(filepath, 'wb') as f:
                    f.write(response.content)
                
                return True
                
            except (requests.exceptions.ConnectionError, 
                    requests.exceptions.Timeout,
                    requests.exceptions.ChunkedEncodingError) as e:
                # These are retryable errors
                if attempt < max_retries - 1:
                    wait_time = (2 ** attempt)  # Exponential backoff: 1s, 2s, 4s
                    console.print(f"[yellow]Download failed (attempt {attempt + 1}/{max_retries}), retrying in {wait_time}s: {e}[/yellow]")
                    time.sleep(wait_time)
                    continue
                else:
                    console.print(f"[red]Failed to download {url} after {max_retries} attempts: {e}[/red]")
                    return False
                    
            except Exception as e:
                # Non-retryable errors (404, 403, etc.)
                console.print(f"[red]Failed to download {url}: {e}[/red]")
                return False
        
        return False
    
    def create_pdf(self, images_dir: Path, output_path: Path, title: str, dpi: int = 150):
        """Create a PDF from downloaded images with pages sized to match each image."""
        console.print(f"[blue]Creating PDF with custom page sizes (DPI: {dpi})...[/blue]")
        
        # Get all image files
        image_files = []
        for ext in ['*.jpg', '*.jpeg', '*.png', '*.gif', '*.webp']:
            image_files.extend(images_dir.glob(ext))
        
        # Sort by filename (assuming sequential naming)
        image_files.sort(key=lambda x: x.name)
        
        if not image_files:
            console.print("[red]No images found for PDF creation[/red]")
            return
        
        from reportlab.platypus import BaseDocTemplate, PageTemplate, Frame
        from reportlab.lib.units import inch
        
        # Create a custom document template that allows different page sizes
        class CustomDocTemplate(BaseDocTemplate):
            def __init__(self, filename, **kwargs):
                BaseDocTemplate.__init__(self, filename, **kwargs)
                self.page_templates = []
        
        try:
            doc = CustomDocTemplate(str(output_path), title=title, author="Comic Compiler")
            
            # We'll build the story manually to handle different page sizes
            from reportlab.pdfgen import canvas
            from reportlab.lib.pagesizes import letter
            
            # Create the PDF using canvas for full control
            c = canvas.Canvas(str(output_path))
            c.setTitle(title)
            c.setAuthor("Comic Compiler")
            
            with Progress() as progress:
                pdf_task = progress.add_task("Creating PDF...", total=len(image_files))
                
                for i, img_path in enumerate(image_files):
                    try:
                        # Open image to get dimensions
                        pil_img = Image.open(img_path)
                        img_width, img_height = pil_img.size
                        
                        # Convert pixels to points (72 points per inch)
                        # Lower DPI = larger pages, higher DPI = smaller pages
                        page_width = (img_width * 72) / dpi
                        page_height = (img_height * 72) / dpi
                        
                        # Set the page size for this page
                        c.setPageSize((page_width, page_height))
                        
                        # Update progress with current page info
                        progress.update(pdf_task, advance=1, description=f"Creating PDF... (Page {i+1}/{len(image_files)})")
                        
                        # Draw the image to fill the entire page
                        c.drawImage(str(img_path), 0, 0, width=page_width, height=page_height)
                        
                        # Start a new page (except for the last image)
                        if i < len(image_files) - 1:
                            c.showPage()
                            
                    except Exception as e:
                        console.print(f"[red]Error processing {img_path}: {e}[/red]")
            
            # Save the PDF
            c.save()
            console.print(f"[green]PDF created with custom page sizes: {output_path}[/green]")
            
        except Exception as e:
            console.print(f"[red]Error building custom PDF: {e}[/red]")
            console.print("[yellow]Falling back to standard PDF format...[/yellow]")
            # Fallback to the original method
            self.create_standard_pdf(images_dir, output_path, title)
    
    def create_standard_pdf(self, images_dir: Path, output_path: Path, title: str):
        """Create a standard PDF with fixed page sizes as fallback."""
        console.print("[blue]Creating standard PDF...[/blue]")
        
        # Get all image files
        image_files = []
        for ext in ['*.jpg', '*.jpeg', '*.png', '*.gif', '*.webp']:
            image_files.extend(images_dir.glob(ext))
        
        # Sort by filename (assuming sequential naming)
        image_files.sort(key=lambda x: x.name)
        
        if not image_files:
            console.print("[red]No images found for PDF creation[/red]")
            return
        
        # Use larger margins to ensure images fit
        margin = 36  # 0.5 inch margin
        doc = SimpleDocTemplate(
            str(output_path),
            pagesize=letter,
            title=title,
            author="Comic Compiler",
            topMargin=margin,
            bottomMargin=margin,
            leftMargin=margin,
            rightMargin=margin
        )
        
        story = []
        
        with Progress() as progress:
            pdf_task = progress.add_task("Creating standard PDF...", total=len(image_files))
            
            for i, img_path in enumerate(image_files):
                try:
                    # Open image to get dimensions
                    pil_img = Image.open(img_path)
                    img_width, img_height = pil_img.size
                    
                    # Get page dimensions
                    page_width, page_height = letter
                    available_width = page_width - (2 * margin)
                    available_height = page_height - (2 * margin)
                    
                    # Calculate scale to fit within available space with safety buffer
                    safety_buffer = 0.95  # Use 95% of available space for safety
                    max_width = available_width * safety_buffer
                    max_height = available_height * safety_buffer
                    
                    scale_x = max_width / img_width
                    scale_y = max_height / img_height
                    scale = min(scale_x, scale_y, 1.0)  # Don't upscale
                    
                    # Ensure reasonable minimum scale
                    scale = max(scale, 0.1)
                    
                    scaled_width = img_width * scale
                    scaled_height = img_height * scale
                    
                    # Final safety check
                    if scaled_width > max_width:
                        scaled_width = max_width
                        scaled_height = (scaled_width / img_width) * img_height
                    
                    if scaled_height > max_height:
                        scaled_height = max_height
                        scaled_width = (scaled_height / img_height) * img_width
                    
                    # Add image to story
                    rl_img = RLImage(str(img_path), width=scaled_width, height=scaled_height)
                    story.append(rl_img)
                    
                    # Add page break except for last image
                    if i < len(image_files) - 1:
                        story.append(PageBreak())
                    
                    # Update progress
                    progress.update(pdf_task, advance=1, description=f"Creating standard PDF... (Page {i+1}/{len(image_files)})")
                        
                except Exception as e:
                    console.print(f"[red]Error processing {img_path}: {e}[/red]")
        
        # Build PDF
        try:
            doc.build(story)
            console.print(f"[green]Standard PDF created: {output_path}[/green]")
        except Exception as e:
            console.print(f"[red]Error building standard PDF: {e}[/red]")
    
    def create_epub(self, images_dir: Path, output_path: Path, title: str):
        """Create an EPUB from downloaded images."""
        console.print("[blue]Creating EPUB...[/blue]")
        
        # Get all image files
        image_files = []
        for ext in ['*.jpg', '*.jpeg', '*.png', '*.gif', '*.webp']:
            image_files.extend(images_dir.glob(ext))
        
        # Sort by filename
        image_files.sort(key=lambda x: x.name)
        
        if not image_files:
            console.print("[red]No images found for EPUB creation[/red]")
            return
        
        book = epub.EpubBook()
        book.set_identifier('comic-compiler-' + str(hash(title)))
        book.set_title(title)
        book.set_language('en')
        book.add_author('Comic Compiler')
        
        # Create chapters for images
        chapters = []
        cover_set = False
        
        with Progress() as progress:
            epub_task = progress.add_task("Creating EPUB...", total=len(image_files))
            
            for i, img_path in enumerate(image_files):
                try:
                    # Read and encode image
                    with open(img_path, 'rb') as img_file:
                        img_data = img_file.read()
                    
                    # Determine image type
                    img_ext = img_path.suffix.lower()
                    if img_ext == '.jpg':
                        img_ext = '.jpeg'
                    
                    mime_type = f'image/{img_ext[1:]}'
                    
                    # Create image item
                    img_name = f'image_{i:03d}{img_ext}'
                    img_item = epub.EpubImage(uid=f'img_{i}', file_name=img_name, 
                                            media_type=mime_type, content=img_data)
                    book.add_item(img_item)
                    
                    # Use the first image as the cover
                    if i == 0 and not cover_set:
                        book.set_cover(img_name, img_data)
                        cover_set = True
                    
                    # Create HTML chapter
                    chapter_content = f'''<!DOCTYPE html>
<html>
<head>
    <title>Page {i + 1}</title>
    <style>
        body {{ margin: 0; padding: 0; text-align: center; }}
        img {{ max-width: 100%; height: auto; }}
    </style>
</head>
<body>
    <img src="{img_name}" alt="Page {i + 1}"/>
</body>
</html>'''
                    
                    chapter = epub.EpubHtml(title=f'Page {i + 1}', 
                                          file_name=f'page_{i:03d}.xhtml',
                                          content=chapter_content)
                    book.add_item(chapter)
                    chapters.append(chapter)
                    
                    # Update progress
                    progress.update(epub_task, advance=1, description=f"Creating EPUB... (Page {i+1}/{len(image_files)})")
                    
                except Exception as e:
                    console.print(f"[red]Error processing {img_path} for EPUB: {e}[/red]")
        
        # Add navigation
        book.toc = [(epub.Section('Pages'), chapters)]
        book.add_item(epub.EpubNcx())
        book.add_item(epub.EpubNav())
        
        # Set spine
        book.spine = ['nav'] + chapters
        
        # Write EPUB
        epub.write_epub(str(output_path), book)
        console.print(f"[green]EPUB created: {output_path}[/green]")
    
    def process_comic_series(self, base_url: str, end_number: int, output_format: str = "both", pdf_dpi: int = 150) -> bool:
        """Process a series of comic issues."""
        console.print(Panel(
            Text(f"Comic Compiler\nProcessing: {base_url}\nEnd number: {end_number}\nFormat: {output_format}\nPDF DPI: {pdf_dpi}", justify="center"),
            style="bold blue"
        ))
        
        # Extract the base URL pattern
        url_pattern = base_url.rstrip('/')
        
        # Find the number pattern in the URL
        number_match = re.search(r'-(\d+)/?$', url_pattern)
        if not number_match:
            console.print("[red]Could not find number pattern in URL[/red]")
            return False
        
        start_number = int(number_match.group(1))
        number_length = len(number_match.group(1))
        base_pattern = url_pattern[:number_match.start(1)]
        url_suffix = url_pattern[number_match.end(1):]
        
        console.print(f"[blue]Detected start number: {start_number}[/blue]")
        console.print(f"[blue]Will process issues {start_number} to {end_number}[/blue]")
        
        comic_title = None
        total_files_created = 0
        
        for issue_num in range(start_number, end_number + 1):
            # Format number with leading zeros if original had them
            formatted_num = str(issue_num).zfill(number_length)
            issue_url = f"{base_pattern}{formatted_num}{url_suffix}"
            
            console.print(f"\n[cyan]Processing issue {issue_num}...[/cyan]")
            
            title, images = self.get_comic_images(issue_url)
            if not comic_title:
                # Use the first issue's title as the series title
                comic_title = re.sub(r'#?\d+.*$', '', title).strip()
                if not comic_title:
                    comic_title = title
            
            if not images:
                console.print(f"[yellow]No images found for issue {issue_num}, skipping...[/yellow]")
                continue
            
            # Create output directory for this comic series
            safe_title = re.sub(r'[^\w\s-]', '', comic_title).strip()
            safe_title = re.sub(r'[-\s]+', '-', safe_title)
            comic_dir = self.output_dir / safe_title
            issue_dir = comic_dir / f"issue-{issue_num:02d}"
            images_dir = issue_dir / 'images'
            images_dir.mkdir(parents=True, exist_ok=True)
            
            # Download images for this issue
            console.print(f"[blue]Downloading {len(images)} images for issue {issue_num}...[/blue]")
            
            downloaded_count = 0
            with Progress() as progress:
                download_task = progress.add_task(f"Downloading issue {issue_num}...", total=len(images))
                
                for i, img_url in enumerate(images):
                    # Generate filename
                    img_ext = Path(urlparse(img_url).path).suffix or '.jpg'
                    img_filename = f"{i+1:04d}{img_ext}"
                    img_path = images_dir / img_filename
                    
                    if self.download_image(img_url, img_path):
                        downloaded_count += 1
                    
                    progress.update(download_task, advance=1)
                    time.sleep(0.5)  # Rate limiting
            
            if downloaded_count == 0:
                console.print(f"[red]No images downloaded for issue {issue_num}, skipping...[/red]")
                continue
            
            console.print(f"[green]Downloaded {downloaded_count}/{len(images)} images for issue {issue_num}[/green]")
            
            # Create PDF and/or EPUB for this issue
            issue_title = f"{comic_title} #{issue_num:02d}"
            pdf_path = issue_dir / f"{safe_title}-{issue_num:02d}.pdf"
            epub_path = issue_dir / f"{safe_title}-{issue_num:02d}.epub"
            
            created_files = []
            
            if output_format in ["both", "pdf"]:
                self.create_pdf(images_dir, pdf_path, issue_title, pdf_dpi)
                created_files.append(f"PDF: {pdf_path.name}")
                total_files_created += 1
            
            if output_format in ["both", "epub"]:
                self.create_epub(images_dir, epub_path, issue_title)
                created_files.append(f"EPUB: {epub_path.name}")
                total_files_created += 1
            
            files_info = ", ".join(created_files)
            console.print(f"[green]Created {files_info} for issue {issue_num}[/green]")
            
            # Be nice to the server between issues
            time.sleep(1)
        
        # Final summary
        if total_files_created > 0:
            console.print(Panel(
                Text(f"Successfully processed {comic_title}\n"
                     f"Output directory: {self.output_dir / safe_title}\n"
                     f"Created {total_files_created} files for issues {start_number} to {end_number}\n"
                     f"Each issue saved in its own subdirectory", justify="center"),
                style="bold green",
                title="Success"
            ))
            return True
        else:
            console.print("[red]No files were created successfully[/red]")
            return False


def main():
    parser = argparse.ArgumentParser(
        description="Download comic pages and convert them to PDF and EPUB formats",
        epilog="""
Examples:
  %(prog)s "https://grabber.zone/comics/sonic-idw/sonic-the-hedgehog-01/" 10 ./output
  %(prog)s "https://grabber.zone/comics/sonic-idw/sonic-the-hedgehog-05/" 15 ~/Comics --format pdf
  %(prog)s "https://grabber.zone/comics/sonic-idw/sonic-the-hedgehog-01/" 3 ./output --format epub
  %(prog)s "https://grabber.zone/comics/sonic-idw/sonic-the-hedgehog-01/" 5 ./output --dpi 200
        """,
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    parser.add_argument('base_url', help='Base URL of the first comic issue')
    parser.add_argument('end_number', type=int, help='Last issue number to download')
    parser.add_argument('output_dir', help='Output directory for downloaded comics')
    parser.add_argument('--format', '-f', choices=['both', 'pdf', 'epub'], 
                       default='both', help='Output format (default: both)')
    parser.add_argument('--dpi', type=int, default=150,
                       help='DPI for PDF page sizing - lower values create larger pages (default: 150)')
    
    args = parser.parse_args()
    
    # Validate arguments
    if not args.base_url.startswith('http'):
        console.print("[red]Error: base_url must start with http:// or https://[/red]")
        sys.exit(1)
    
    if args.end_number < 1:
        console.print("[red]Error: end_number must be positive[/red]")
        sys.exit(1)
    
    if args.dpi < 50 or args.dpi > 600:
        console.print("[red]Error: DPI must be between 50 and 600[/red]")
        sys.exit(1)
    
    # Create compiler and process
    compiler = ComicCompiler(args.output_dir)
    
    try:
        success = compiler.process_comic_series(args.base_url, args.end_number, args.format, args.dpi)
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        console.print("\n[yellow]Operation cancelled by user[/yellow]")
        sys.exit(1)
    except Exception as e:
        console.print(f"[red]Unexpected error: {e}[/red]")
        sys.exit(1)


if __name__ == "__main__":
    main()