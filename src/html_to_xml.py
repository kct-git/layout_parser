from bs4 import BeautifulSoup

def convert_html_to_repx(html_content, start_ref=1000):
    """
    Parses an HTML table and converts it into DevExpress XRTable XML
    suitable for IFS Report Studio. Includes Virtual Grid Normalization
    to inject placeholder cells for accurate RowSpan rendering.
    """
    soup = BeautifulSoup(html_content, 'html.parser')
    table = soup.find('table')
    
    if not table:
        return "Error: No <table> tag found in the provided HTML."

    # Global reference counter for unique DevExpress 'Ref' IDs
    ref_counter = start_ref
    def get_ref():
        nonlocal ref_counter
        ref_counter += 1
        return ref_counter

    # 1. First Pass: Build the Virtual Grid
    # We map (row_idx, col_idx) to cell properties or a 'skip' marker
    grid = {}
    html_rows = table.find_all('tr')
    max_cols = 0
    
    for r_idx, row in enumerate(html_rows):
        c_idx = 0
        for html_cell in row.find_all(['th', 'td']):
            
            # Advance column index past any cells occupied by rowspans from above
            while (r_idx, c_idx) in grid:
                c_idx += 1
                
            colspan = int(html_cell.get('colspan', 1))
            rowspan = int(html_cell.get('rowspan', 1))
            text = html_cell.get_text(strip=True)
            is_header = html_cell.name == 'th'
            
            # Register the actual HTML parent cell
            grid[(r_idx, c_idx)] = {
                'weight': colspan,
                'rowspan': rowspan,
                'text': text,
                'is_header': is_header,
                'is_dummy': False
            }
            
            # 2. Track intersections and inject Dummy Cells
            for r in range(rowspan):
                for c in range(colspan):
                    if r == 0 and c == 0:
                        continue # Parent cell is already handled
                    
                    # If the span reaches into a new row, we MUST place a dummy cell
                    # at the very beginning of that span's footprint for DevExpress.
                    if r > 0 and c == 0:
                        grid[(r_idx + r, c_idx)] = {
                            'weight': colspan,
                            'rowspan': 1, # Dummies don't span rows
                            'text': '',
                            'is_header': False,
                            'is_dummy': True
                        }
                    # For wide colspans (c > 0), we just mark the grid space as 'skip' 
                    # so we don't accidentally place another HTML cell here.
                    elif r > 0 and c > 0:
                        grid[(r_idx + r, c_idx + c)] = 'skip'
                    elif r == 0 and c > 0:
                        grid[(r_idx, c_idx + c)] = 'skip'
            
            c_idx += colspan
            max_cols = max(max_cols, c_idx)

    # 3. Second Pass: Generate the DevExpress XML
    xml_output = []
    
    table_ref = get_ref()
    xml_output.append(f'<Item1 Ref="{table_ref}" ControlType="XRTable" Name="table{table_ref}" SizeF="980,100" LocationFloat="0,0" Dpi="96" Borders="All">')
    xml_output.append('  <Rows>')

    total_rows = len(html_rows)
    for r_idx in range(total_rows):
        row_item_num = r_idx + 1
        row_ref = get_ref()
        
        xml_output.append(f'    <Item{row_item_num} Ref="{row_ref}" ControlType="XRTableRow" Name="tr{row_ref}" Weight="1" Dpi="96">')
        xml_output.append('      <Cells>')
        
        c_idx = 0
        cell_item_num = 1
        
        while c_idx < max_cols:
            cell_data = grid.get((r_idx, c_idx))
            
            # If it's a 'skip' marker, it means a cell to our left is currently
            # spanning across this column. We just move forward.
            if cell_data == 'skip' or cell_data is None:
                c_idx += 1
                continue
                
            cell_ref = get_ref()
            weight = cell_data['weight']
            rowspan = cell_data['rowspan']
            text = cell_data['text']
            is_header = cell_data['is_header']
            is_dummy = cell_data['is_dummy']
            
            # Format XML attributes
            weight_attr = f' Weight="{weight}"'
            rowspan_attr = f' RowSpan="{rowspan}"' if rowspan > 1 else ""
            
            # Escape XML special characters
            safe_text = text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')
            text_attr = f' Text="{safe_text}"' if safe_text else ""
            
            # Styling logic
            if is_header and not is_dummy:
                font_attr = ' Font="Arial, 9.75pt, style=Bold"'
            else:
                font_attr = ' Font="Arial, 9pt"'
                
            # Construct node
            node = f'        <Item{cell_item_num} Ref="{cell_ref}" ControlType="XRTableCell" Name="tc{cell_ref}"{weight_attr}{rowspan_attr}{text_attr}{font_attr} Dpi="96" />'
            xml_output.append(node)
            
            cell_item_num += 1
            c_idx += weight # Jump ahead by the width of the cell
            
        xml_output.append('      </Cells>')
        xml_output.append(f'    </Item{row_item_num}>')

    xml_output.append('  </Rows>')
    xml_output.append('</Item1>')

    return '\n'.join(xml_output)

# ==========================================
# Execution Block
# ==========================================
if __name__ == "__main__":
    html_input = """
<table>
      <tr>
        <th colspan="8">Test Results</th>
      </tr>
      <tr>
        <td colspan="5">It is important to keep a record of the combustion analysis results - if they have been carried out electronically a copyof the printout should be attached to all copies of the service schedule and report.</td>
        <td>Print out attached?</td>
        <td>Yes ☐</td>
        <td>No ☐</td>
      </tr>
      <tr>
        <td>Pump pressure:</td>
        <td></td>
        <td>Efficiency Nett (%):</td>
        <td></td>
        <td colspan="2">Efficiency Gross:</td>
        <td colspan="2"></td>
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
        <td colspan="2">Flow rate (oil) Low (cc/min)</td>
        <td></td>
        <td colspan="2">High (cc/min)</td>
        <td></td>
      </tr>
      <tr>
        <td>Flue gas temp (°C)</td>
        <td></td>
        <td colspan="2">Flow rate (DHW) Cold (l/min)</td>
        <td></td>
        <td colspan="2">Hot (l/min)</td>
        <td></td>
      </tr>
      <tr>
        <td>Recipient’s name:</td>
        <td colspan="3"></td>
        <td colspan="2">Recipient’s signature:</td>
        <td colspan="2"></td>
      </tr>
      <tr>
        <td>Date:</td>
        <td></td>
        <td>Recipient’s status:</td>
        <td></td>
        <td colspan="4"></td>
      </tr>
      <tr>
        <td>Technician’s name:</td>
        <td colspan="3"></td>
        <td colspan="2">Technician’s signature:</td>
        <td colspan="2"></td>
      </tr>
      <tr>
        <td>Date:</td>
        <td></td>
        <td colspan="6"></td>
      </tr>
    </table>
    """
    
    print("Converting Normalized HTML to IFS .rep XML...\n")
    print(convert_html_to_repx(html_input))