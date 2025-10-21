#!/usr/bin/env python3
"""
Script to embed symbol_modal.css and symbol_modal.js inline into dashboard.html
"""

import os

# Paths
template_dir = '/projects/ngTradingBot/templates'
dashboard_path = os.path.join(template_dir, 'dashboard.html')
css_path = os.path.join(template_dir, 'symbol_modal.css')
js_path = os.path.join(template_dir, 'symbol_modal.js')

# Read the files
with open(dashboard_path, 'r', encoding='utf-8') as f:
    dashboard_content = f.read()

with open(css_path, 'r', encoding='utf-8') as f:
    css_content = f.read()

with open(js_path, 'r', encoding='utf-8') as f:
    js_content = f.read()

# Replace the placeholders
old_css_marker = """    <!-- Symbol Modal CSS (Inline) -->
    <style>
        <?php include 'symbol_modal.css'; ?>
    </style>"""

new_css_marker = f"""    <!-- Symbol Modal CSS (Inline) -->
    <style>
{css_content}
    </style>"""

old_js_marker = """    <!-- Symbol Modal JavaScript (Inline) -->
    <script>
        <?php include 'symbol_modal.js'; ?>
    </script>"""

new_js_marker = f"""    <!-- Symbol Modal JavaScript (Inline) -->
    <script>
{js_content}
    </script>"""

# Replace
dashboard_content = dashboard_content.replace(old_css_marker, new_css_marker)
dashboard_content = dashboard_content.replace(old_js_marker, new_js_marker)

# Write back
with open(dashboard_path, 'w', encoding='utf-8') as f:
    f.write(dashboard_content)

print("✅ Successfully embedded symbol_modal.css and symbol_modal.js into dashboard.html")
print(f"   CSS: {len(css_content)} characters")
print(f"   JS: {len(js_content)} characters")
