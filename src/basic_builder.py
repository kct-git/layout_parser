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


def generate_table_xml(html_rows, loc_x, relative_y, table_width, table_height, get_ref_func, item_idx):
    """Generates XRTable XML using the virtual grid logic with strict weight balancing."""
    if not html_rows:
        return ""
        
    table_ref = get_ref_func()
    xml_output = []
    
    # 1. Virtual Grid Pass (Unchanged)
    grid = {}
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
    xml_output.append(f'        <Item{item_idx} Ref="{table_ref}" ControlType="XRTable" Name="table{table_ref}" SizeF="{table_width:.2f},{table_height:.2f}" LocationFloat="{loc_x:.2f},{relative_y:.2f}" Dpi="96" Borders="All" Padding="2,2,0,0,96">')
    xml_output.append('          <Rows>')

    for r_idx in range(total_rows):
        row_ref = get_ref_func()
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
                
            node = f'                <Item{cell_item_num} Ref="{cell_ref}" ControlType="XRTableCell" Name="tc{cell_ref}" Weight="{weight}"{rowspan_attr} Text="{text}"{font_attr}{back_color} ForeColor="Black" TextAlignment="MiddleLeft" Dpi="96" />'
            xml_output.append(node)
            
            cell_item_num += 1
            c_idx += weight 
            
        xml_output.append('              </Cells>')
        xml_output.append(f'            </Item{r_idx + 1}>')

    xml_output.append('          </Rows>')
    xml_output.append(f'        </Item{item_idx}>')
    return '\n'.join(xml_output)


def convert_html_to_repx(html_content, start_ref=100):
    soup = BeautifulSoup(html_content, 'html.parser')
    
    ref_counter = start_ref
    def get_ref():
        nonlocal ref_counter
        ref_counter += 1
        return ref_counter

    bands_data = {
        "TopMarginBand": {"items": [], "min_y": float('inf'), "max_y": 0},
        "ReportHeaderBand": {"items": [], "min_y": float('inf'), "max_y": 0},
        "DetailBand": {"items": [], "min_y": float('inf'), "max_y": 0},
        "GroupHeaderBand": {"items": [], "min_y": float('inf'), "max_y": 0},
        "DetailReportBand": {
            "sub_reports": [], 
            "min_y": float('inf'), "max_y": 0
        },
        "GroupFooterBand": {"items": [], "min_y": float('inf'), "max_y": 0},
        "ReportFooterBand": {"items": [], "min_y": float('inf'), "max_y": 0},
        "PageFooterBand": {"items": [], "min_y": float('inf'), "max_y": 0},
        "BottomMarginBand": {"items": [], "min_y": float('inf'), "max_y": 0}
    }

    for div in soup.find_all('div', attrs={'data-label': True}):
        label = div.get('data-label', '')
        bbox = div.get('data-bbox')
        loc_x, loc_y, width, height = calculate_dimensions(bbox)
        
        target_band_ref = None
        is_sub_report = False
        
        if "Top-Margin" in label:
            target_band_ref = bands_data["TopMarginBand"]
        elif "Report-Header" in label:
            target_band_ref = bands_data["ReportHeaderBand"]
        elif "Detail-Band" in label:
            target_band_ref = bands_data["DetailBand"]
        elif "Group-Header" in label:
            target_band_ref = bands_data["GroupHeaderBand"]
        elif "Detail-Report" in label or "Detail" in label:
            target_band_ref = bands_data["DetailReportBand"]
            is_sub_report = True
        elif "Group-Footer" in label:
            target_band_ref = bands_data["GroupFooterBand"]
        elif "Report-Footer" in label:
            target_band_ref = bands_data["ReportFooterBand"]
        elif "Page-Footer" in label:
            target_band_ref = bands_data["PageFooterBand"]
        elif "Bottom-Margin" in label:
            target_band_ref = bands_data["BottomMarginBand"]
        else:
            target_band_ref = bands_data["DetailReportBand"]
            is_sub_report = True
            
        if is_sub_report:
            target_band_ref["sub_reports"].append({
                "div": div, "label": label, 
                "x": loc_x, "y": loc_y, "w": width, "h": height
            })
        else:
            target_band_ref["items"].append({
                "div": div, "label": label, 
                "x": loc_x, "y": loc_y, "w": width, "h": height
            })
            
        target_band_ref["min_y"] = min(target_band_ref["min_y"], loc_y)
        target_band_ref["max_y"] = max(target_band_ref["max_y"], loc_y + height)

    def generate_controls_xml(items, band_min_y, get_ref, starting_idx=1):
        controls_xml = []
        control_idx = starting_idx
        for item in items:
            relative_y = item["y"] - band_min_y
            
            if "Picture" in item["label"]:
                pic_ref = get_ref()
                controls_xml.append(f'        <Item{control_idx} Ref="{pic_ref}" ControlType="XRPictureBox" Name="pic{pic_ref}" SizeF="{item["w"]:.2f},{item["h"]:.2f}" LocationFloat="{item["x"]:.2f},{relative_y:.2f}" Dpi="96" Sizing="ZoomImage" />')
                control_idx += 1
            
            elif "Table" in item["label"]:
                table_node = item["div"].find('table')
                if table_node:
                    html_rows = table_node.find_all('tr')
                    table_xml = generate_table_xml(html_rows, item["x"], relative_y, item["w"], item["h"], get_ref, control_idx)
                    controls_xml.append(table_xml)
                    control_idx += 1
            
            else:
                lbl_ref = get_ref()
                text = " ".join([t.get_text() for t in item["div"].find_all(['h1', 'h2', 'p', 'span'])]) if item["div"].find(['h1', 'h2']) else item["div"].get_text(strip=True)
                controls_xml.append(f'        <Item{control_idx} Ref="{lbl_ref}" ControlType="XRLabel" Name="lbl{lbl_ref}" SizeF="{item["w"]:.2f},{item["h"]:.2f}" LocationFloat="{item["x"]:.2f},{relative_y:.2f}" Text="{text}" Font="Arial, 10pt" Dpi="96" TextAlignment="MiddleCenter" />')
                control_idx += 1
        return controls_xml

    xml_output = [
        '<?xml version="1.0" encoding="utf-8"?>',
        f'<XtraReportsLayoutSerializer SerializerVersion="23.2.4.0" Ref="1" ControlType="DevExpress.XtraReports.UI.XtraReport" Name="GeneratedRep" SnapGridSize="12.5" ReportUnit="Pixels" Margins="{MARGIN_LEFT}, {MARGIN_RIGHT}, {MARGIN_TOP}, {MARGIN_BOTTOM}" PaperKind="Custom" PageWidth="{int(PAGE_WIDTH_PX)}" PageHeight="{int(PAGE_HEIGHT_PX)}" Version="23.2" Dpi="96">',
        '  <Bands>'
    ]

    band_idx = 1
    for band_name, band_data in bands_data.items():
        band_ref = get_ref()
        short_name = band_name.replace("Band", "")
        if band_name not in ["TopMarginBand", "BottomMarginBand"]:
            short_name += "1"
            
        if band_name == "DetailReportBand":
            has_sub_reports = len(band_data.get("sub_reports", [])) > 0
            
        if band_name == "DetailReportBand":
            has_sub_reports = len(band_data.get("sub_reports", [])) > 0
            
            if not has_sub_reports:
                xml_output.append(f'    <Item{band_idx} Ref="{band_ref}" ControlType="{band_name}" Name="{short_name}" Level="0" Dpi="96">')
                xml_output.append('      <ReportPrintOptions DetailCountOnEmptyDataSource="1" />')
                xml_output.append(f'    </Item{band_idx}>')
                band_idx += 1
            else:
                sub_report_level = 0
                for sub_item in band_data["sub_reports"]:
                    sub_ref = get_ref()
                    sub_name = f"DetailReport{sub_report_level + 1}"
                    xml_output.append(f'    <Item{band_idx} Ref="{sub_ref}" ControlType="DetailReportBand" Name="{sub_name}" Level="{sub_report_level}" Dpi="96">')
                    xml_output.append('      <ReportPrintOptions DetailCountOnEmptyDataSource="1" />')
                    xml_output.append('      <Bands>')
                    
                    if "Table" in sub_item["label"]:
                        table_node = sub_item["div"].find('table')
                        if table_node:
                            html_rows = table_node.find_all('tr')
                            header_rows = [tr for tr in html_rows if tr.find('th')]
                            data_rows = [tr for tr in html_rows if tr.find('td') and not tr.find('th')]
                            
                            band_inner_idx = 1
                            if header_rows:
                                gh_ref = get_ref()
                                gh_height = sub_item["h"] / len(html_rows) * len(header_rows) if len(html_rows) > 0 else 25.0
                                xml_output.append(f'        <Item{band_inner_idx} Ref="{gh_ref}" ControlType="GroupHeaderBand" Name="GroupHeader_{sub_ref}" HeightF="{gh_height:.2f}" Dpi="96">')
                                xml_output.append('          <Controls>')
                                table_xml = generate_table_xml(header_rows, sub_item["x"], 0, sub_item["w"], gh_height, get_ref, 1)
                                if table_xml:
                                    indented_str = '\n'.join(['    ' + line for line in table_xml.split('\n')])
                                    xml_output.append(indented_str)
                                xml_output.append('          </Controls>')
                                xml_output.append(f'        </Item{band_inner_idx}>')
                                band_inner_idx += 1
                                
                            if data_rows:
                                db_ref = get_ref()
                                db_height = sub_item["h"] / len(html_rows) * len(data_rows) if len(html_rows) > 0 else 25.0
                                xml_output.append(f'        <Item{band_inner_idx} Ref="{db_ref}" ControlType="DetailBand" Name="Detail_{sub_ref}" HeightF="{db_height:.2f}" Dpi="96">')
                                xml_output.append('          <Controls>')
                                table_xml = generate_table_xml(data_rows, sub_item["x"], 0, sub_item["w"], db_height, get_ref, 1)
                                if table_xml:
                                    indented_str = '\n'.join(['    ' + line for line in table_xml.split('\n')])
                                    xml_output.append(indented_str)
                                xml_output.append('          </Controls>')
                                xml_output.append(f'        </Item{band_inner_idx}>')
                    else:
                        # Non-table item
                        gh_ref = get_ref()
                        xml_output.append(f'        <Item1 Ref="{gh_ref}" ControlType="GroupHeaderBand" Name="GroupHeader_{sub_ref}" HeightF="{sub_item["h"]:.2f}" Dpi="96">')
                        xml_output.append('          <Controls>')
                        controls_xml = generate_controls_xml([sub_item], sub_item["y"], get_ref, 1) 
                        for control_str in controls_xml:
                            indented_str = '\n'.join(['    ' + line for line in control_str.split('\n')])
                            xml_output.append(indented_str)
                        xml_output.append('          </Controls>')
                        xml_output.append('        </Item1>')
                        
                    xml_output.append('      </Bands>')
                    xml_output.append(f'    </Item{band_idx}>')
                    band_idx += 1
                    sub_report_level += 1
        else:
            if band_data.get("items"):
                band_min_y = band_data["min_y"]
                band_height = band_data["max_y"] - band_min_y + 20 
            else:
                if band_name == "TopMarginBand":
                    band_height = MARGIN_TOP
                elif band_name == "BottomMarginBand":
                    band_height = MARGIN_BOTTOM
                else:
                    band_height = 0.0

            if not band_data.get("items"):
                xml_output.append(f'    <Item{band_idx} Ref="{band_ref}" ControlType="{band_name}" Name="{short_name}" HeightF="{band_height:.2f}" Dpi="96" />')
            else:
                xml_output.append(f'    <Item{band_idx} Ref="{band_ref}" ControlType="{band_name}" Name="{short_name}" HeightF="{band_height:.2f}" Dpi="96">')
                xml_output.append('      <Controls>')
                controls_xml = generate_controls_xml(band_data["items"], band_min_y, get_ref)
                xml_output.extend(controls_xml)
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
    <div data-bbox="[17,14,137,79]" data-label="Report-Header-Picture">[Figure: JLA logo]</div>

<div data-bbox="[211,28,784,77]" data-label="Report-Header-Title">Plant Commissioning/Servicing Record (Non-Domestic)</div>

<div data-bbox="[885,34,974,240]" data-label="Report-Header-Picture">[Figure: Gas Safe Register logo with registration number 537976]</div>

<div data-bbox="[22,86,856,275]" data-label="Report-Header-Table">
<table>
  <tr>
    <th>Inspection No:</th>
    <td></td>
    <th>Company:</th>
    <td></td>
    <th>Inspection Address:</th>
    <th>Customer Address:</th>
  </tr>
  <tr>
    <td colspan="2" rowspan="3"></td>
    <th>Address:</th>
    <td></td>
    <td rowspan="3"></td>
    <td rowspan="3"></td>
  </tr>
  <tr>
    <th>Tel No:</th>
    <td></td>
  </tr>
  <tr>
    <th>Engineer Name:</th>
    <td></td>
  </tr>
  <tr>
    <td colspan="2"></td>
    <th>Gas Safe Reg No:</th>
    <td></td>
    <th>Inspection Date:</th>
    <td>Page 1 of 1</td>
  </tr>
</table>
</div>

<div data-bbox="[22,280,945,407]" data-label="Detail-Report-Table">
<table>
  <tr>
    <th colspan="7">Appliance Details</th>
    <th colspan="16">Combustion Checks</th>
  </tr>
  <tr>
    <th>Location</th>
    <th>Type</th>
    <th>Make / Model</th>
    <th>Serial Number</th>
    <th>Burner Manufacturer</th>
    <th>Flue Type</th>
    <th>Firing Mode</th>
    <th>Heat input rating (kW)</th>
    <th>Gas burner pressure (mbar)</th>
    <th>Gas rate (m&sup3;/hr)</th>
    <th>Air/gas ratio control setting</th>
    <th>Ambient (room) temp (&deg;C)</th>
    <th>Flue gas temp (&deg;C)</th>
    <th>Flue gas temp net (&deg;C)</th>
    <th>Flue draught pressure (mbar)</th>
    <th>Oxygen (O2) %</th>
    <th>Carbon Monoxide (CO) ppm</th>
    <th>Carbon Dioxide (CO2) %</th>
    <th>NOx %</th>
    <th>Excess air %</th>
    <th>CO/CO2-ratio</th>
    <th>Gross efficiency %</th>
    <th>CO flue dilution ppm</th>
  </tr>
  <tr>
    <td rowspan="2"></td>
    <td rowspan="2"></td>
    <td rowspan="2"></td>
    <td rowspan="2"></td>
    <td rowspan="2"></td>
    <td rowspan="2"></td>
    <td>Low</td>
    <td></td>
    <td></td>
    <td></td>
    <td></td>
    <td></td>
    <td></td>
    <td></td>
    <td></td>
    <td></td>
    <td></td>
    <td></td>
    <td></td>
    <td></td>
    <td></td>
    <td></td>
    <td></td>
  </tr>
  <tr>
    <td>High</td>
    <td></td>
    <td></td>
    <td></td>
    <td></td>
    <td></td>
    <td></td>
    <td></td>
    <td></td>
    <td></td>
    <td></td>
    <td></td>
    <td></td>
    <td></td>
    <td></td>
    <td></td>
    <td></td>
  </tr>
</table>
</div>

<div data-bbox="[22,408,945,482]" data-label="Detail-Report-Table">
<table>
  <tr>
    <th colspan="4">Additional Checks (Yes/No/NA)</th>
  </tr>
  <tr>
    <td>Flue flow test satisfactory</td>
    <td>Ventilation satisfactory (see also Ventilation type)?</td>
    <td>Flame proving/safety devices operating correctly?</td>
    <td>Burner lock-out time (seconds)?</td>
  </tr>
  <tr>
    <td>Spillage test satisfactory?</td>
    <td>Temperature and limit thermostats operating correctly?</td>
    <td>Air/gas pressure switch operating correctly?</td>
    <td>Appliance serviced?</td>
  </tr>
</table>
</div>

<div data-bbox="[23,490,945,704]" data-label="Detail-Report-Table">
<table>
  <tr>
    <th>General Safety Checks (Yes/No/NA)</th>
    <th>Ventilation type</th>
    <th>Safety Information (Yes/No)</th>
    <th>If Warning/Advice Notice issued, insert Serial No*</th>
  </tr>
  <tr>
    <td>Gas booster(s)/compressor(s) operating correctly?</td>
    <td>Natural: Room/boiler room/enclosure low-level free area (cm&sup2;)</td>
    <td>Has a Warning/Advice Notice been raised?</td>
    <td rowspan="7"></td>
  </tr>
  <tr>
    <td>Gas installation tightness test carried out (if Yes, see separate form)?</td>   
    <td>Natural: Room/boiler room/enclosure high-level free area (cm&sup2;)</td>        
    <td>Have warning labels been attached?</td>
  </tr>
  <tr>
    <td>Gas installation pipework adequately supported?</td>
    <td>Natural: Is ventilation satisfactory? (If No, see Details of remedial work required)</td>
    <td>Has responsible person been advised?</td>
  </tr>
  <tr>
    <td>Gas installation pipework sleeved/labelled/painted as necessary?</td>
    <td>Mechanical: ventilation flow rate inlet (m&sup3;/s)</td>
    <td rowspan="4">*Refer to separate Warning/Advice Notice</td>
  </tr>
  <tr>
    <td>Chimney system installed in accordance with appropriate standards?</td>
    <td>Mechanical: ventilation flow rate extract (m&sup3;/s)</td>
  </tr>
  <tr>
    <td>Chimney outlet termination(s) satisfactory?</td>
    <td>Mechanical: ventilation interlock operating correctly?</td>
  </tr>
  <tr>
    <td>Fan-flue interlock operating correctly?</td>
    <td>Mechanical: Is ventilation satisfactory? (If No, see Remedial work required)</td>
  </tr>
</table>
</div>

<div data-bbox="[23,705,945,799]" data-label="Detail-Report-Table">
<table>
  <tr>
    <th>Details of work carried out</th>
    <th>General Safety Checks (Yes/No/NA)</th>
  </tr>
  <tr>
    <td></td>
    <td></td>
  </tr>
</table>
</div>

<div data-bbox="[20,804,507,904]" data-label="Report-Footer-Text">**DECLARATION OF GAS SAFETY** - I confirm that all of the above work described on this form has been satisfactorily completed in accordance with the current Gas Safety (Installation and Use) Regulations, standards and procedures.</div>

<div data-bbox="[464,806,947,875]" data-label="Report-Footer-Table">
<table>
  <tr>
    <th>Engineer name:</th>
    <td></td>
    <th>Received by:</th>
    <td></td>
  </tr>
  <tr>
    <th>Signature:</th>
    <td></td>
    <th>Signature:</th>
    <td></td>
  </tr>
</table>
</div>

<div data-bbox="[20,883,162,908]" data-label="Report-Footer-Text">Card ID: 5783555</div>

<div data-bbox="[332,883,745,908]" data-label="Report-Footer-Footnote">Gas Safe Register is a registered trade mark of the HSE and is used under licence.</div>

<div data-bbox="[806,883,848,908]" data-label="Report-Footer-Text">CP15</div>

<div data-bbox="[20,930,800,980]" data-label="Page-Footer-Footnote">JLA Limited, a company incorporated in England and Wales with company number 01094178, whose registered address is Meadowcroft Lane, Halifax Road, Ripponden, Sowerby Bridge, HX6 4AJ. JLA Total Care Limited, a company incorporated in England and Wales with company number 02951461, whose registered address is Meadowcroft Lane, Halifax Road, Ripponden, Sowerby Bridge, HX6 4AJ. JLA Total Care Limited is authorised and regulated by the Financial Conduct Authority Reference No. 631198</div>

<div data-bbox="[833,936,978,980]" data-label="Page-Footer-Text">jla.com | 0800 591 903</div>
    """
    
    rep_xml = convert_html_to_repx(html_input)
    
    with open("MultiBandReport.rep", "w", encoding="utf-8") as file:
        file.write(rep_xml)
        
    print("Successfully generated MultiBandReport.rep!")