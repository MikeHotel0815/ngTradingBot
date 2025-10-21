#!/usr/bin/env python3
"""
Script to re-embed symbol_modal.js by replacing the existing embedded version
"""

# Read the dashboard file
with open('/projects/ngTradingBot/templates/dashboard.html', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Read the complete symbol_modal.js
with open('/projects/ngTradingBot/templates/symbol_modal.js', 'r', encoding='utf-8') as f:
    js_content = f.read()

# Find the start and end of the embedded JavaScript
js_start = None
js_end = None

for i, line in enumerate(lines):
    if '<!-- Symbol Modal JavaScript (Inline) -->' in line:
        js_start = i
    elif js_start is not None and js_end is None:
        # Look for the closing script tag after "SymbolModal.init();"
        if '</script>' in line and i > js_start + 10:
            # Check if this is the right closing tag by looking for SymbolModal in previous lines
            found_symbol_modal = False
            for j in range(max(0, i - 50), i):
                if 'SymbolModal' in lines[j]:
                    found_symbol_modal = True
                    break
            if found_symbol_modal:
                js_end = i + 1  # Include the closing tag
                break

print(f"Found JavaScript block: lines {js_start} to {js_end}")

if js_start is not None and js_end is not None:
    # Create the new JavaScript block
    new_js_block = [
        '    <!-- Symbol Modal JavaScript (Inline) -->\n',
        '    <script>\n'
    ]

    # Add each line of the JS content
    for line in js_content.split('\n'):
        new_js_block.append(line + '\n')

    new_js_block.append('    </script>\n')
    new_js_block.append('\n')

    # Replace the old block with the new one
    new_lines = lines[:js_start] + new_js_block + lines[js_end:]

    # Write back
    with open('/projects/ngTradingBot/templates/dashboard.html', 'w', encoding='utf-8') as f:
        f.writelines(new_lines)

    print(f"✅ Successfully replaced symbol_modal.js")
    print(f"   Old block: {js_end - js_start} lines")
    print(f"   New block: {len(new_js_block)} lines")
    print(f"   JS content: {len(js_content)} characters")
else:
    print("❌ Could not find JavaScript block markers")
    print(f"   js_start: {js_start}")
    print(f"   js_end: {js_end}")
