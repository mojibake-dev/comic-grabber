# Comic Compiler

A Python script that scrapes comic pages from free comic websites and compiles them into PDF or EPUB formats. Currently works with grabber.zone, with plans to support additional sites.

## What It Does

Takes a comic URL, downloads all the images from the reading content, and packages them into clean output. The PDF version creates custom page sizes that match each image. The EPUB version uses the first page as the cover image and creates a proper ebook structure.

## Installation

Clone this repo and set up the Python environment:

```bash
git clone https://github.com/mojibake-dev/comic-compiler.git
cd comic-compiler
python -m venv venv
source venv/bin/activate  # On macOS/Linux
pip install -r requirements.txt
```

## Usage

Basic usage:
```bash
python main.py "https://grabber.zone/comics/sonic-idw/sonic-the-hedgehog-01/" 5 ./output
```

This downloads issues 1-5 of Sonic IDW and creates both PDF and EPUB files in the output directory.

### Arguments

- `base_url`: URL of the first comic issue
- `end_number`: Last issue number to download  
- `output_dir`: Where to save the files

### Options

- `--format pdf|epub|both`: Choose output format (default: both)
- `--dpi 50-600`: PDF page sizing - lower DPI = larger pages (default: 150)

### Examples

Just PDF with larger pages:
```bash
python main.py "https://grabber.zone/comics/sonic-idw/sonic-the-hedgehog-01/" 3 ./comics --format pdf --dpi 100
```

Just EPUB:
```bash
python main.py "https://grabber.zone/comics/sonic-idw/sonic-the-hedgehog-01/" 1 ./comics --format epub
```

## How It Works

1. Scrapes the page and finds images in the `reading-content` div
2. Downloads all images at full resolution
3. For PDF: Creates pages sized exactly to each image using ReportLab
4. For EPUB: Packages images into proper ebook structure with ebooklib
5. Names files with issue numbers (e.g., `Sonic-The-Hedgehog-01-to-05.pdf`)

## Current Limitations

- Only works with grabber.zone right now
- Assumes sequential issue numbering in URLs
- No retry logic for failed downloads
- Rate limited to be respectful to servers

## Planned Features

- Support for additional comic sites
- Batch processing multiple series
- Better error handling and retry logic
- Comic metadata extraction
- Custom naming patterns

## Why This Exists

Free comic sites are great but reading in a browser can be clunky and the continued existence is up to the existene of the page. Having offline copies in standard formats means you can read them properly on tablets, e-readers, or archive them however you want. The PDF generation specifically avoids the typical "shrink images to fit letter-size pages" approach that makes comics unreadable.

## Dependencies

- requests + beautifulsoup4 for scraping
- Pillow for image processing  
- reportlab for PDF generation
- ebooklib for EPUB creation
- rich for terminal output

## License

Do whatever you want with this code. If it breaks your computer, that's on you.
