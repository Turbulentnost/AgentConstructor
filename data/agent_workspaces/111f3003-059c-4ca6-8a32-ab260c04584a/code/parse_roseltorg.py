import json
import re
from html.parser import HTMLParser

# Read the HTML file
with open('page_dumps/roseltorg_procedures_20260709_091227/page.html', 'r', encoding='utf-8') as f:
    html_content = f.read()

# The Roseltorg table uses ExtJS grid. Let's find table rows.
# ExtJS grids typically use div-based structures, not <table> elements.
# Let's look for the grid row pattern.

# Try BeautifulSoup approach
try:
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html_content, 'html.parser')
except ImportError:
    # Fallback: use regex-based parsing
    soup = None

results = []

if soup:
    # ExtJS grid rows are typically in divs with class containing 'x-grid3-row'
    rows = soup.find_all('div', class_=re.compile(r'x-grid3-row'))
    
    if not rows:
        # Try finding table rows
        rows = soup.find_all('tr', class_=re.compile(r'x-grid3-row'))
    
    if not rows:
        # Try another pattern - look for the grid table
        tables = soup.find_all('table')
        print(f"Found {len(tables)} tables in HTML")
        
        # Look for grid body
        grid_body = soup.find_all('div', class_=re.compile(r'x-grid'))
        print(f"Found {len(grid_body)} grid elements")
        
        # Let's search for procedure numbers pattern
        proc_pattern = re.compile(r'COM\d+|\d{11,}')
        proc_matches = proc_pattern.findall(html_content)
        print(f"Found {len(proc_matches)} procedure number matches: {proc_matches[:5]}")
        
        # Look for specific class patterns in the HTML
        class_patterns = re.findall(r'class="[^"]*grid[^"]*"', html_content[:50000])
        print(f"Grid class patterns (first 10): {class_patterns[:10]}")
        
        # Search for row-related classes
        row_patterns = re.findall(r'class="[^"]*row[^"]*"', html_content[:100000])
        unique_row_patterns = list(set(row_patterns))[:20]
        print(f"Row class patterns (unique, first 20): {unique_row_patterns}")
    else:
        print(f"Found {len(rows)} grid rows")
        for row in rows:
            cells = row.find_all('td')
            if cells:
                cell_texts = [cell.get_text(strip=True) for cell in cells]
                print(f"Row cells: {cell_texts}")
else:
    # Regex-based parsing
    print("BeautifulSoup not available, using regex")
    # Find procedure numbers
    proc_pattern = re.compile(r'(COM\d+|\d{11,})')
    proc_matches = proc_pattern.findall(html_content)
    print(f"Found procedure numbers: {proc_matches[:30]}")
    
    # Look for the structure around procedure numbers
    # Find first occurrence and print surrounding context
    first_match = re.search(r'COM09072600016', html_content)
    if first_match:
        start = max(0, first_match.start() - 200)
        end = min(len(html_content), first_match.end() + 500)
        print(f"\nContext around first procedure:\n{html_content[start:end]}")

print("\n--- Script completed ---")
