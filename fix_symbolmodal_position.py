#!/usr/bin/env python3
"""
Fix SymbolModal JavaScript position - move it before the main script block
"""

# Read the dashboard file
with open('/projects/ngTradingBot/templates/dashboard.html', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Find the markers
symbol_modal_js_start = None
symbol_modal_js_end = None
main_script_start = None

for i, line in enumerate(lines):
    if '<!-- Symbol Modal JavaScript (Inline) -->' in line:
        symbol_modal_js_start = i
    elif symbol_modal_js_start is not None and symbol_modal_js_end is None:
        # Look for the closing script tag after the start
        if '</script>' in line:
            symbol_modal_js_end = i + 1  # Include the closing tag
    if '// Initialize Socket.IO with explicit configuration' in line:
        main_script_start = i - 1  # The <script> tag before this comment

print(f"Symbol Modal JS: lines {symbol_modal_js_start} to {symbol_modal_js_end}")
print(f"Main script starts at: {main_script_start}")

if symbol_modal_js_start and symbol_modal_js_end and main_script_start:
    # Extract the SymbolModal script block
    symbol_modal_block = lines[symbol_modal_js_start:symbol_modal_js_end]

    # Remove it from the original position
    new_lines = lines[:symbol_modal_js_start] + lines[symbol_modal_js_end:]

    # Adjust main_script_start after removal
    if main_script_start > symbol_modal_js_start:
        main_script_start -= (symbol_modal_js_end - symbol_modal_js_start)

    # Insert before main script with a blank line
    symbol_modal_block.append('\n')
    new_lines = new_lines[:main_script_start] + symbol_modal_block + new_lines[main_script_start:]

    # Write back
    with open('/projects/ngTradingBot/templates/dashboard.html', 'w', encoding='utf-8') as f:
        f.writelines(new_lines)

    print(f"✅ Successfully moved SymbolModal JavaScript")
    print(f"   Moved from line {symbol_modal_js_start} to line {main_script_start}")
    print(f"   Block size: {symbol_modal_js_end - symbol_modal_js_start} lines")
else:
    print("❌ Could not find all markers")
    print(f"   symbol_modal_js_start: {symbol_modal_js_start}")
    print(f"   symbol_modal_js_end: {symbol_modal_js_end}")
    print(f"   main_script_start: {main_script_start}")
