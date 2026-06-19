import json
from bs4 import BeautifulSoup

# Match IFS Default Dimensions
PAGE_WIDTH_PX = 793.0
PAGE_HEIGHT_PX = 1056.0
MARGIN_LEFT = 56.69
MARGIN_RIGHT = 37.80
MARGIN_TOP = 1.92
MARGIN_BOTTOM = 1.00

# Calculate the actual printable area
USABLE_WIDTH = PAGE_WIDTH_PX - MARGIN_LEFT - MARGIN_RIGHT

def calculate_dimensions(bbox_str):
    """Converts normalized [0-1000] bounding boxes to Margin-Relative 96-DPI pixels."""
    if not bbox_str:
        return 0, 0, 100, 25
        
    x1, y1, x2, y2 = json.loads(bbox_str)
    
    # 1. Calculate absolute pixels from the page edges
    abs_loc_x = (x1 / 1000.0) * PAGE_WIDTH_PX
    abs_loc_y = (y1 / 1000.0) * PAGE_HEIGHT_PX
    width = ((x2 - x1) / 1000.0) * PAGE_WIDTH_PX
    height = ((y2 - y1) / 1000.0) * PAGE_HEIGHT_PX
    
    # 2. Translate absolute X to Margin-Relative X
    # If the LLM box starts inside the margin space, snap it to 0 (the margin edge)
    rel_loc_x = abs_loc_x - MARGIN_LEFT
    if rel_loc_x < 0:
        rel_loc_x = 0.0 
        
    # 3. Prevent width overflow
    # If the table width spills past the right margin, clamp it to the usable width
    if rel_loc_x + width > USABLE_WIDTH:
        width = USABLE_WIDTH - rel_loc_x
        
    return rel_loc_x, abs_loc_y, width, height


def generate_table_xml(table_soup, loc_x, relative_y, table_width, table_height, get_ref_func, item_idx):
    """Generates XRTable XML using the virtual grid logic with strict weight balancing."""
    table_ref = get_ref_func()
    xml_output = []
    
    # 1. Virtual Grid Pass (Unchanged)
    grid = {}
    html_rows = table_soup.find_all('tr')
    max_cols = 0
    total_rows = len(html_rows)
    row_height = table_height / total_rows if total_rows > 0 else 25.0
    
    for r_idx, row in enumerate(html_rows):
        c_idx = 0
        for html_cell in row.find_all(['th', 'td']):
            while (r_idx, c_idx) in grid:
                c_idx += 1
                
            colspan = int(html_cell.get('colspan', 1))
            rowspan = int(html_cell.get('rowspan', 1))
            text = html_cell.get_text(strip=True)
            is_header = html_cell.name == 'th'
            
            grid[(r_idx, c_idx)] = {'weight': colspan, 'rowspan': rowspan, 'text': text, 'is_header': is_header, 'is_dummy': False}
            
            for r in range(rowspan):
                for c in range(colspan):
                    if r == 0 and c == 0: continue 
                    if r > 0 and c == 0:
                        grid[(r_idx + r, c_idx)] = {'weight': colspan, 'rowspan': 1, 'text': '', 'is_header': False, 'is_dummy': True}
                    elif r > 0 and c > 0: grid[(r_idx + r, c_idx + c)] = 'skip'
                    elif r == 0 and c > 0: grid[(r_idx, c_idx + c)] = 'skip'
            
            c_idx += colspan
            max_cols = max(max_cols, c_idx)

    # 2. Table XML Generation
    # FIX: Use the passed item_idx ONLY for the root XRTable node
    xml_output.append(f'        <Item{item_idx} Ref="{table_ref}" ControlType="XRTable" Name="table{table_ref}" SizeF="{table_width:.2f},{table_height:.2f}" LocationFloat="{loc_x:.2f},{relative_y:.2f}" Dpi="96" Borders="All" Padding="2,2,0,0,96">')
    xml_output.append('          <Rows>')

    for r_idx in range(total_rows):
        row_ref = get_ref_func()
        # Internal rows always start at Item1, Item2, etc.
        xml_output.append(f'            <Item{r_idx + 1} Ref="{row_ref}" ControlType="XRTableRow" Name="tr{row_ref}" SizeF="{table_width:.2f},{row_height:.2f}" Weight="1" Dpi="96">')
        xml_output.append('              <Cells>')
        
        c_idx = 0
        cell_item_num = 1
        while c_idx < max_cols:
            cell_data = grid.get((r_idx, c_idx))
            
            if cell_data == 'skip':
                c_idx += 1
                continue
                
            if cell_data is None:
                cell_data = {'weight': 1, 'rowspan': 1, 'text': '', 'is_header': False, 'is_dummy': True}
                
            cell_ref = get_ref_func()
            weight, rowspan = cell_data['weight'], cell_data['rowspan']
            text = cell_data['text'].replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')
            
            rowspan_attr = f' RowSpan="{rowspan}"' if rowspan > 1 else ""
            font_attr = ' Font="Arial, 10pt, style=Bold"' if cell_data['is_header'] and not cell_data['is_dummy'] else ' Font="Arial, 9pt"'
            back_color = ' BackColor="255,230,230,230"' if cell_data['is_header'] and not cell_data['is_dummy'] else ' BackColor="White"'
                
            # Internal cells always start at Item1, Item2, etc.
            node = f'                <Item{cell_item_num} Ref="{cell_ref}" ControlType="XRTableCell" Name="tc{cell_ref}" Weight="{weight}"{rowspan_attr} Text="{text}"{font_attr}{back_color} ForeColor="Black" TextAlignment="MiddleLeft" Dpi="96" />'
            xml_output.append(node)
            
            cell_item_num += 1
            c_idx += weight 
            
        xml_output.append('              </Cells>')
        xml_output.append(f'            </Item{r_idx + 1}>')

    xml_output.append('          </Rows>')
    # FIX: Close with the passed item_idx
    xml_output.append(f'        </Item{item_idx}>')
    return '\n'.join(xml_output)


def convert_html_to_repx(html_content, start_ref=100):
    soup = BeautifulSoup(html_content, 'html.parser')
    
    ref_counter = start_ref
    def get_ref():
        nonlocal ref_counter
        ref_counter += 1
        return ref_counter

    # 1. Group Elements by Band
    bands_data = {
        "ReportHeaderBand": {"items": [], "min_y": float('inf'), "max_y": 0},
        "DetailBand": {"items": [], "min_y": float('inf'), "max_y": 0}
        # DetailReportBand instead of DetailBand
        # ReportFooter Band
        # PageFooter Band
        # TopMargin / BottomMargin
    }

    for div in soup.find_all('div', attrs={'data-label': True}):
        label = div.get('data-label', '')
        bbox = div.get('data-bbox')
        loc_x, loc_y, width, height = calculate_dimensions(bbox)
        
        # Route based on prefix
        target_band = "ReportHeaderBand" if "Report-Header" in label else "DetailBand"
        
        bands_data[target_band]["items"].append({
            "div": div, "label": label, 
            "x": loc_x, "y": loc_y, "w": width, "h": height
        })
        
        # Track band boundaries to calculate total height and relative offsets later
        bands_data[target_band]["min_y"] = min(bands_data[target_band]["min_y"], loc_y)
        bands_data[target_band]["max_y"] = max(bands_data[target_band]["max_y"], loc_y + height)

    # 2. Generate XML Orchestration
    # xml_output = [
    #     '<?xml version="1.0" encoding="utf-8"?>',
    #     '<XtraReportsLayoutSerializer SerializerVersion="23.2.4.0" Ref="1" ControlType="DevExpress.XtraReports.UI.XtraReport" Name="GeneratedRep" PageWidth="793" PageHeight="1122" Version="23.2" Dpi="96" ReportUnit="Pixels">',
    #     '  <Bands>'
    # ]

    xml_output = [
        '<?xml version="1.0" encoding="utf-8"?>',
        f'<XtraReportsLayoutSerializer SerializerVersion="23.2.4.0" Ref="1" ControlType="DevExpress.XtraReports.UI.XtraReport" Name="GeneratedRep" SnapGridSize="12.5" ReportUnit="Pixels" Margins="{MARGIN_LEFT}, {MARGIN_RIGHT}, {MARGIN_TOP}, {MARGIN_BOTTOM}" PaperKind="Custom" PageWidth="{int(PAGE_WIDTH_PX)}" PageHeight="{int(PAGE_HEIGHT_PX)}" Version="23.2" Dpi="96">',
        '  <Bands>'
    ]

    band_idx = 1
    for band_name, band_data in bands_data.items():
        if not band_data["items"]:
            continue # Skip empty bands

        band_ref = get_ref()
        band_min_y = band_data["min_y"]
        # Calculate how tall the band needs to be to fit all its items
        band_height = band_data["max_y"] - band_min_y + 20 
        
        xml_output.append(f'    <Item{band_idx} Ref="{band_ref}" ControlType="{band_name}" Name="{band_name.replace("Band", "")}" HeightF="{band_height:.2f}" Dpi="96">')
        xml_output.append('      <Controls>')
        
        for item_idx, item in enumerate(band_data["items"]):
            # CRUCIAL: DevExpress items are positioned relative to their parent band!
            relative_y = item["y"] - band_min_y
            
            if "Picture" in item["label"]:
                pic_ref = get_ref()
                xml_output.append(f'        <Item{item_idx+1} Ref="{pic_ref}" ControlType="XRPictureBox" Name="pic{pic_ref}" SizeF="{item["w"]:.2f},{item["h"]:.2f}" LocationFloat="{item["x"]:.2f},{relative_y:.2f}" Dpi="96" Sizing="ZoomImage" />')
            
            elif "Title" in item["label"] or "Text" in item["label"]:
                lbl_ref = get_ref()
                # Extract text from h1/h2 tags
                text = " ".join([t.get_text() for t in item["div"].find_all(['h1', 'h2', 'p', 'span'])]) if item["div"].find(['h1', 'h2']) else item["div"].get_text(strip=True)
                xml_output.append(f'        <Item{item_idx+1} Ref="{lbl_ref}" ControlType="XRLabel" Name="lbl{lbl_ref}" SizeF="{item["w"]:.2f},{item["h"]:.2f}" LocationFloat="{item["x"]:.2f},{relative_y:.2f}" Text="{text}" Font="Arial, 14pt, style=Bold" Dpi="96" TextAlignment="MiddleCenter" />')
            
            elif "Table" in item["label"]:
                table_node = item["div"].find('table')
                if table_node:
                    # Pass item_idx+1 directly into the function
                    table_xml = generate_table_xml(table_node, item["x"], relative_y, item["w"], item["h"], get_ref, item_idx+1)
                    xml_output.append(table_xml)

        xml_output.append('      </Controls>')
        xml_output.append(f'    </Item{band_idx}>')
        band_idx += 1

    xml_output.append('  </Bands>')
    xml_output.append('</XtraReportsLayoutSerializer>')

    return '\n'.join(xml_output)


# ==========================================
# Execution Block
# ==========================================
if __name__ == "__main__":
    
    html_input = """
    <div data-bbox="[36,18,170,86]" data-label="Report-Header-Picture">[Figure: JLA logo]</div>

<div data-bbox="[290,15,715,80]" data-label="Report-Header-Title"><h1>CD/11</h1><h2>Oil Firing Servicing and Commissioning Report</h2></div>

<div data-bbox="[848,10,968,92]" data-label="Report-Header-Picture">[Figure: OFTEC Registered Business logo]</div>

<div data-bbox="[39,95,977,120]" data-label="Report-Header-Table">
<table>
  <tr>
    <th>Inspection No:</th>
    <td></td>
  </tr>
</table>
</div>

<div data-bbox="[39,126,977,245]" data-label="Report-Header-Table">
<table>
  <tr>
    <th colspan="2">Details of Registered Business</th>
    <th>Site Address</th>
    <th>Customer Address</th>
  </tr>
  <tr>
    <td>Business name:</td>
    <td></td>
    <td rowspan="5"></td>
    <td rowspan="4"></td>
  </tr>
  <tr>
    <td>OFTEC Co Reg No</td>
    <td></td>
  </tr>
  <tr>
    <td>Engineers name:</td>
    <td></td>
  </tr>
  <tr>
    <td>Technician’s Reg No:</td>
    <td></td>
  </tr>
  <tr>
    <td>Address:</td>
    <td></td>
    <td>Page 1 of 1</td>
  </tr>
</table>
</div>

<div data-bbox="[39,256,977,333]" data-label="Detail-Report-Table">
<table>
  <tr>
    <th colspan="4">Pre-commissioning checks / legislation</th>
  </tr>
  <tr>
    <td colspan="3">1. Is there a completed CD/10 (or equivalent) for the installation works?</td>
    <td></td>
  </tr>
  <tr>
    <td>2. If the Installer is not a Competent Person, is there a Building Notice?</td>
    <td></td>
    <td>If Yes, insert Ref. No.</td>
    <td></td>
  </tr>
</table>
</div>

<div data-bbox="[39,340,977,420]" data-label="Detail-Report-Table">
<table>
  <tr>
    <th colspan="4">Appliance Details</th>
  </tr>
  <tr>
    <td>Appliance Make Model</td>
    <td colspan="3"></td>
  </tr>
  <tr>
    <td>Appliance Serial No.:</td>
    <td></td>
    <td>Burner Make Model:</td>
    <td></td>
  </tr>
  <tr>
    <td>Tank Type:</td>
    <td></td>
    <td>Type:</td>
    <td></td>
  </tr>
  <tr>
    <td>Fuel Type:</td>
    <td></td>
    <td>Flue Type:</td>
    <td></td>
  </tr>
</table>
</div>

<div data-bbox="[39,430,977,455]" data-label="Detail-Report-Section-header"><h3>Call Type</h3></div>

<div data-bbox="[39,456,977,764]" data-label="Detail-Report-Table">
<table>
  <tr>
    <th colspan="5">Oil firing service and Commissioning schedule (Confirm in accordance with checklists on the reverse and tick as appropriate)</th>
  </tr>
  <tr>
    <th>No.</th>
    <th>Schedule Item</th>
    <th>Checked?</th>
    <th>Passed?</th>
    <th>Parts fitted / Observations</th>
  </tr>
  <tr><td>1.</td><td>Oil storage</td><td></td><td></td><td></td></tr>
  <tr><td>2.</td><td>Oil supply system</td><td></td><td></td><td></td></tr>
  <tr><td>3.</td><td>Air Supply</td><td></td><td></td><td></td></tr>
  <tr><td>4.</td><td>Chimney/Flue</td><td></td><td></td><td></td></tr>
  <tr><td>5.</td><td>Electrical safety</td><td></td><td></td><td></td></tr>
  <tr><td>6.</td><td>Heat Exchanger</td><td></td><td></td><td></td></tr>
  <tr><td>7.</td><td>Combustion chamber</td><td></td><td></td><td></td></tr>
  <tr><td>8.</td><td>Pressure jet burner</td><td></td><td></td><td></td></tr>
  <tr><td>9.</td><td>Vaporising and wallflame burner</td><td></td><td></td><td></td></tr>
  <tr><td>10.</td><td>Wallflame burner (additional)</td><td></td><td></td><td></td></tr>
  <tr><td>11.</td><td>Appliance safety controls</td><td></td><td></td><td></td></tr>
  <tr>
    <th colspan="5">Heating system service</th>
  </tr>
  <tr><td>12.</td><td>Controls check</td><td></td><td></td><td></td></tr>
  <tr><td>13.</td><td>System check - Hot water type</td><td></td><td></td><td></td></tr>
  <tr><td>14.</td><td>System check - Warm air type</td><td></td><td></td><td></td></tr>
</table>
</div>

<div data-bbox="[39,773,977,891]" data-label="Report-Footer-Table">
<table>
  <tr>
    <th colspan="8">Test Results</th>
  </tr>
  <tr>
    <td colspan="5">It is important to keep a record of the combustion analysis results - if they have been carried out electronically a copy of the printout should be attached to all copies of the service schedule and report.</td>
    <td>Print out attached?</td>
    <td>Yes ☐</td>
    <td>No ☐</td>
  </tr>
  <tr>
    <td>Pump pressure:</td>
    <td></td>
    <td>Efficiency Nett (%):</td>
    <td></td>
    <td>Efficiency Gross:</td>
    <td></td>
    <td></td>
    <td></td>
  </tr>
  <tr>
    <td>Pump vacumn:</td>
    <td></td>
    <td>Smoke No.</td>
    <td></td>
    <td>CO (ppm)</td>
    <td></td>
    <td>Excess Air (%)</td>
    <td></td>
  </tr>
  <tr>
    <td>Draught:</td>
    <td></td>
    <td>Nozzle (size):</td>
    <td></td>
    <td>(angle)</td>
    <td></td>
    <td>(pattern)</td>
    <td></td>
  </tr>
  <tr>
    <td>CO₂ (%)</td>
    <td></td>
    <td>Flow rate (oil)</td>
    <td></td>
    <td>Low (cc/min)</td>
    <td></td>
    <td>High (cc/min)</td>
    <td></td>
  </tr>
  <tr>
    <td>Flue gas temp (°C)</td>
    <td></td>
    <td>Flow rate (DHW)</td>
    <td></td>
    <td>Cold (l/min)</td>
    <td></td>
    <td>Hot (l/min)</td>
    <td></td>
  </tr>
</table>
</div>

<div data-bbox="[39,892,977,955]" data-label="Report-Footer-Table">
<table>
  <tr>
    <td>Recipient’s name:</td>
    <td colspan="3"></td>
    <td rowspan="2">Recipient’s signature:</td>
    <td rowspan="2"></td>
  </tr>
  <tr>
    <td>Date:</td>
    <td></td>
    <td>Recipient’s status:</td>
    <td></td>
  </tr>
  <tr>
    <td>Technician’s name:</td>
    <td colspan="3"></td>
    <td rowspan="2">Technician’s signature:</td>
    <td rowspan="2"></td>
  </tr>
  <tr>
    <td>Date:</td>
    <td colspan="3"></td>
  </tr>
</table>
</div>

<div data-bbox="[31,957,792,998]" data-label="Page-Footer-Footnote">JLA Limited, a company incorporated in England and Wales with company number 01094178, whose registered address is Meadowcroft Lane, Halifax Road, Ripponden, Sowerby Bridge, HX6 4AJ. JLA Total Care Limited, a company incorporated in England and Wales with company number 02951461, whose registered address is Meadowcroft Lane, Halifax Road, Ripponden, Sowerby Bridge, HX6 4AJ. JLA Total Care Limited is authorised and regulated by the Financial Conduct Authority Reference No. 631198</div>

<div data-bbox="[796,958,978,995]" data-label="Page-Footer-Text">jla.com | 0800 591 903</div>
    """
    
    rep_xml = convert_html_to_repx(html_input)
    
    with open("MultiBandReport.rep", "w", encoding="utf-8") as file:
        file.write(rep_xml)
        
    print("Successfully generated MultiBandReport.rep!")