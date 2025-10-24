from google.oauth2.service_account import Credentials
import gspread
import os
import pandas as pd
import requests
import re
from logan import Logan
from configuration import MCNF

def get_spreadsheet(read_only=False):
    """
    Get Google Spreadsheet with optional read-only mode.
    
    Args:
        read_only (bool): If True, uses public CSV export when credentials are missing
    
    Returns:
        Spreadsheet object or ReadOnlySpreadsheet wrapper for read-only mode
    """
    spreadsheet_url = os.getenv("SPREADSHEET_URL")
    if not spreadsheet_url:
        raise ValueError("SPREADSHEET_URL environment variable is not set")
    
    # Check for credentials
    creds_file = 'credentials.json' if os.path.exists('credentials.json') else '../credentials.json'
    
    if not os.path.exists(creds_file):
        if read_only:
            return ReadOnlySpreadsheet(spreadsheet_url)
        else:
            raise FileNotFoundError(f"Credentials file not found at {creds_file}. Use read_only=True for read-only access.")
    
    # Normal authenticated access
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    credentials = Credentials.from_service_account_file(creds_file, scopes=scope)
    client = gspread.authorize(credentials)
    spreadsheet = client.open_by_url(spreadsheet_url)
    return spreadsheet

class ReadOnlySpreadsheet:
    """Read-only wrapper for Google Sheets using public CSV export"""
    
    def __init__(self, spreadsheet_url):
        self.spreadsheet_url = spreadsheet_url
        self.sheet_id = self._extract_sheet_id(spreadsheet_url)
        
    def _extract_sheet_id(self, url):
        """Extract sheet ID from Google Sheets URL"""
        match = re.search(r'/spreadsheets/d/([a-zA-Z0-9-_]+)', url)
        if not match:
            raise ValueError("Invalid Google Sheets URL")
        return match.group(1)
    
    def worksheet(self, title):
        """Return a read-only worksheet"""
        return ReadOnlyWorksheet(self.sheet_id, title)

class ReadOnlyWorksheet:
    """Read-only worksheet that fetches data via CSV export"""
    
    def __init__(self, sheet_id, title):
        self.sheet_id = sheet_id
        self.title = title
        
    def get_all_records(self):
        """Get all records from the worksheet as a list of dictionaries"""
        try:
            # URL encode the sheet title to handle spaces and special characters
            import urllib.parse
            encoded_title = urllib.parse.quote(self.title)
            
            # Map known sheet names to likely GID positions
            # Based on the sheet order: All Markets, Selected Markets, Hyperparameters
            sheet_gid_mapping = {
                'All Markets': 0, 
                'Selected Markets': 1,
                'Hyperparameters': 2
            }
            
            # Try multiple URL formats for accessing the sheet
            urls_to_try = [
                f"https://docs.google.com/spreadsheets/d/{self.sheet_id}/gviz/tq?tqx=out:csv&sheet={encoded_title}",
                f"https://docs.google.com/spreadsheets/d/{self.sheet_id}/gviz/tq?tqx=out:csv&sheet={self.title}",
            ]
            
            # Add GID-based URL if we know the likely position for this sheet
            if self.title in sheet_gid_mapping:
                gid = sheet_gid_mapping[self.title]
                urls_to_try.append(f"https://docs.google.com/spreadsheets/d/{self.sheet_id}/export?format=csv&gid={gid}")
            
            # Also try a few common GID positions as fallback
            for gid in [0, 1, 2, 3, 4]:
                urls_to_try.append(f"https://docs.google.com/spreadsheets/d/{self.sheet_id}/export?format=csv&gid={gid}")
            
            for csv_url in urls_to_try:
                try:
                    response = requests.get(csv_url, timeout=MCNF.HTTP_TIMEOUT)
                    response.raise_for_status()
                    
                    # Read CSV data into DataFrame
                    from io import StringIO
                    df = pd.read_csv(StringIO(response.text))
                    
                    # Check if we got meaningful data (not empty or error response)
                    if not df.empty and len(df.columns) > 1:
                        # For Hyperparameters sheet, verify it has the expected columns
                        if self.title == 'Hyperparameters':
                            expected_cols = ['type', 'param', 'value']
                            if all(col in df.columns for col in expected_cols):
                                Logan.info(
                                    f"Successfully fetched {len(df)} hyperparameter records",
                                    namespace="poly_utils.google_utils"
                                )
                                return df.to_dict('records')
                            else:
                                Logan.warn(
                                    f"Sheet doesn't match Hyperparameters format. Columns: {list(df.columns)}",
                                    namespace="poly_utils.google_utils"
                                )
                                continue
                        else:
                            Logan.info(
                                f"Successfully fetched {len(df)} records from sheet '{self.title}'",
                                namespace="poly_utils.google_utils"
                            )
                            # Convert to list of dictionaries (same format as gspread)
                            return df.to_dict('records')
                    
                except Exception as url_error:
                    Logan.warn(
                        f"Failed fetching sheet '{self.title}' from URL {csv_url}: {url_error}",
                        namespace="poly_utils.google_utils"
                    )
                    continue
            
            Logan.error(
                f"All URL attempts failed for sheet '{self.title}'",
                namespace="poly_utils.google_utils"
            )
            return []
            
        except Exception as e:
            Logan.error(
                f"Error in get_all_records for Google Sheet '{self.title}'",
                namespace="poly_utils.google_utils",
                exception=e
            )
            return []
    
    def get_all_values(self):
        """Get all values from the worksheet as a list of lists"""
        try:
            csv_url = f"https://docs.google.com/spreadsheets/d/{self.sheet_id}/gviz/tq?tqx=out:csv&sheet={self.title}"
            response = requests.get(csv_url, timeout=MCNF.HTTP_TIMEOUT)
            response.raise_for_status()
            
            # Read CSV and return as list of lists
            from io import StringIO
            df = pd.read_csv(StringIO(response.text))
            
            # Include headers and convert to list of lists
            headers = [df.columns.tolist()]
            data = df.values.tolist()
            return headers + data
            
        except Exception as e:
            Logan.error(
                f"Error in get_all_values for Google Sheet '{self.title}'",
                namespace="poly_utils.google_utils",
                exception=e
            )
            return []
        
def get_sheet_df(read_only=None) -> tuple[pd.DataFrame, dict]:
    """
    Get sheet data with optional read-only mode
    
    Args:
        read_only (bool): If None, auto-detects based on credentials availability
    """
    all = 'All Markets'

    # Auto-detect read-only mode if not specified
    if read_only is None:
        creds_file = 'credentials.json' if os.path.exists('credentials.json') else '../credentials.json'
        read_only = not os.path.exists(creds_file)
        if read_only:
            Logan.info(
                "No credentials found, using read-only mode",
                namespace="poly_data.utils"
            )

    try:
        spreadsheet = get_spreadsheet(read_only=read_only)
    except FileNotFoundError:
        Logan.info(
            "No credentials found, falling back to read-only mode",
            namespace="poly_data.utils"
        )
        spreadsheet = get_spreadsheet(read_only=True)

    # Read directly from All Markets - no more filtering at read time
    wk = spreadsheet.worksheet(all)
    result = pd.DataFrame(wk.get_all_records())
    
    result = result.loc[result['question'] != "", :].reset_index(drop=True)

    wk_p = spreadsheet.worksheet('Hyperparameters')
    records = wk_p.get_all_records()
    hyperparams, current_type = {}, None

    for r in records:
        # Update current_type only when we have a non-empty type value
        # Handle both string and NaN values from pandas
        type_value = r['type']
        if type_value and str(type_value).strip() and str(type_value) != 'nan':
            current_type = str(type_value).strip()
        
        # Skip rows where we don't have a current_type set
        if current_type:
            # Convert numeric values to appropriate types
            value = r['value']
            try:
                # Try to convert to float if it's numeric
                if isinstance(value, str) and value.replace('.', '').replace('-', '').isdigit():
                    value = float(value)
                elif isinstance(value, (int, float)):
                    value = float(value)
            except (ValueError, TypeError):
                pass  # Keep as string if conversion fails
            
            hyperparams.setdefault(current_type, {})[r['param']] = value

    return result, hyperparams



