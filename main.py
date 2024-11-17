from fasthtml.common import *
import os
import json
import zipfile
import pandas as pd
from litellm import completion
from datetime import datetime
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, 
                   format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Constants
UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'zip'}

# LLM System Message
SYSTEM_MESSAGE = """You are a medical assistant providing concise CGM and insulin pump setting recommendations.

ANALYZE AND PROVIDE:
1. ONE specific pattern with exact time period and glucose values
2. ONE basal rate adjustment (single time block only)
3. Realistic, data-based outcome targets

FORMAT YOUR RESPONSE AS:
### Pattern Identified
- State exact time period and glucose values observed (e.g., "Between 2-5 AM: glucose consistently drops from 7.0 to 3.8 mmol/L")

### Recommended Change
- ONE specific basal rate adjustment for ONE time block
- Must include: current rate, new rate, exact start/end times

### Expected Outcome
- State specific, achievable glucose targets for the adjusted time period
- Avoid percentage predictions unless directly supported by the data

IMPORTANT:
- Focus on the most problematic time period only
- No overlapping time blocks
- Base predictions only on available data"""

# Constants and default settings
DEFAULT_SETTINGS = json.loads("""
{
  "timed_settings": [
    {"time_range": "12:00 AM", "basal_rate": 0.4, "correction_factor": "1:3.0", "carb_ratio": "1:10", "target_bg": 6.5},
    {"time_range": "2:00 AM", "basal_rate": 0.5, "correction_factor": "1:3.0", "carb_ratio": "1:10", "target_bg": 6.5},
    {"time_range": "5:00 AM", "basal_rate": 0.8, "correction_factor": "1:3.0", "carb_ratio": "1:10", "target_bg": 6.5},
    {"time_range": "6:00 AM", "basal_rate": 0.9, "correction_factor": "1:3.0", "carb_ratio": "1:10", "target_bg": 6.5},
    {"time_range": "7:00 AM", "basal_rate": 0.8, "correction_factor": "1:3.0", "carb_ratio": "1:10", "target_bg": 5.6},
    {"time_range": "8:00 AM", "basal_rate": 0.8, "correction_factor": "1:2.5", "carb_ratio": "1:10", "target_bg": 5.6},
    {"time_range": "9:00 AM", "basal_rate": 0.45, "correction_factor": "1:2.5", "carb_ratio": "1:10", "target_bg": 5.6},
    {"time_range": "3:00 PM", "basal_rate": 0.5, "correction_factor": "1:2.5", "carb_ratio": "1:10", "target_bg": 5.6},
    {"time_range": "4:00 PM", "basal_rate": 0.6, "correction_factor": "1:2.5", "carb_ratio": "1:10", "target_bg": 5.6},
    {"time_range": "7:00 PM", "basal_rate": 0.45, "correction_factor": "1:2.5", "carb_ratio": "1:12", "target_bg": 5.6},
    {"time_range": "9:00 PM", "basal_rate": 0.3, "correction_factor": "1:3.0", "carb_ratio": "1:12", "target_bg": 5.6},
    {"time_range": "11:00 PM", "basal_rate": 0.3, "correction_factor": "1:3.0", "carb_ratio": "1:10", "target_bg": 5.6}
  ]
}
""")

def parse_time(time_str):
    """Convert time string to 24-hour format integer"""
    try:
        if 'AM' in time_str or 'PM' in time_str:
            return int(datetime.strptime(time_str, "%I:%M %p").strftime("%H"))
        return int(datetime.strptime(time_str, "%H:%M").strftime("%H"))
    except ValueError:
        return None

def format_time(hour):
    """Convert hour to AM/PM format"""
    return datetime.strptime(f"{hour:02d}:00", "%H:%M").strftime("%I:%M %p").lstrip("0")

def convert_settings_to_hourly():
    """Convert default settings to hourly format with proper ordering"""
    hourly_settings = {}
    
    # Convert all times to 24-hour format and store settings
    for setting in DEFAULT_SETTINGS["timed_settings"]:
        hour = parse_time(setting["time_range"])
        if hour is not None:
            hourly_settings[hour] = {
                "basal_rate": setting["basal_rate"],
                "correction_factor": setting["correction_factor"],
                "carb_ratio": setting["carb_ratio"],
                "target_bg": setting["target_bg"]
            }
    
    return hourly_settings

def generate_settings_table():
    """Generate the settings table with default values and proper ordering"""
    hourly_settings = convert_settings_to_hourly()
    
    # Create table rows
    rows = []
    
    # Add header row
    rows.append(Tr(
        Th("Time"),
        Th("Basal Rate (U/hr)"),
        Th("Correction Factor (1:mmol/L)"),
        Th("Carb Ratio (1:grams)"),
        Th("Target BG (mmol/L)"),
        Th("Actions")
    ))
    
    # Get the last settings for filling gaps
    last_settings = {
        "basal_rate": 0.0,
        "correction_factor": "1:3.0",
        "carb_ratio": "1:10",
        "target_bg": 5.6
    }
    
    # Generate rows for each hour, using previous settings for missing hours
    for hour in range(24):
        if hour in hourly_settings:
            last_settings = hourly_settings[hour]
            
        rows.append(Tr(
            Td(format_time(hour)),
            Td(Input(type="number", step="0.1", name=f"basal_rate_{hour}", 
                    value=str(last_settings["basal_rate"]))),
            Td(Input(type="text", name=f"correction_factor_{hour}", 
                    value=last_settings["correction_factor"])),
            Td(Input(type="text", name=f"carb_ratio_{hour}", 
                    value=last_settings["carb_ratio"])),
            Td(Input(type="number", step="0.1", name=f"target_bg_{hour}", 
                    value=str(last_settings["target_bg"]))),
            Td(
                Button("Delete", 
                      type="button",
                      onclick=f"deleteRow(this)",
                      cls="delete-btn"),
                style="text-align: center;"
            )
        ))
    
    # Create and return the table with all rows
    return Table(*rows, cls="settings-table")

# Add custom CSS for the insulin pump settings
CUSTOM_CSS = """
    .settings-table {
        width: 100%;
        border-collapse: collapse;
        font-size: 14px;  /* Smaller font size */
    }
    
    .settings-table th,
    .settings-table td {
        padding: 4px 8px;  /* Reduced padding */
        border: 1px solid #ddd;
    }
    
    .settings-table input {
        width: 100%;
        padding: 2px 4px;  /* Smaller input fields */
        height: 24px;      /* Reduced height */
        margin: 0;
    }
    
    .delete-btn {
        padding: 2px 8px;
        font-size: 12px;
        height: auto;
    }
    
    /* Mobile responsiveness */
    @media (max-width: 768px) {
        .settings-table {
            font-size: 12px;  /* Even smaller on mobile */
        }
        
        .settings-table th,
        .settings-table td {
            padding: 2px 4px;
        }
        
        .content-container {
            padding: 10px;
            margin: 0;
        }
        
        .settings-form {
            overflow-x: auto;  /* Allow horizontal scroll on mobile */
        }
        
        /* Stack the upload and settings sections on mobile */
        .upload-section,
        .settings-form {
            width: 100%;
            margin-bottom: 1em;
        }
    }
"""

# Add JavaScript for row management
CUSTOM_JS = """
function deleteRow(button) {
    const row = button.closest('tr');
    if (document.querySelectorAll('.settings-table tr').length > 2) {
        row.remove();
    } else {
        alert('Cannot delete the last row');
    }
}

function validateForm() {
    const rows = document.querySelectorAll('.settings-table tr');
    const times = new Set();
    
    for (let i = 1; i < rows.length; i++) {
        const timeCell = rows[i].cells[0];
        const time = timeCell.textContent;
        
        if (times.has(time)) {
            alert('Duplicate time entries are not allowed');
            return false;
        }
        times.add(time);
    }
    
    if (rows.length > 25) { // Header + 24 hours
        alert('Maximum 24 time slots allowed');
        return false;
    }
    
    return true;
}
"""

# Initialize FastHTML app
app, rt = fast_app(hdrs=(
    Script(src="https://unpkg.com/htmx.org@1.9.10"),
    Style(CUSTOM_CSS)
))

# Helper functions
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def process_zip_data(file_path, folder_path):
    """Process uploaded zip file and return dataframes"""
    try:
        # Extract the zip file
        with zipfile.ZipFile(file_path, 'r') as zip_ref:
            logger.info(f"Extracting zip file to {folder_path}")
            zip_ref.extractall(folder_path)
        
        # Process the data files
        data = {
            'alarms': pd.read_csv(f'{folder_path}/alarms_data_1.csv', skiprows=1),
            'cgm': pd.read_csv(f'{folder_path}/cgm_data_1.csv', skiprows=1),
            'bolus': pd.read_csv(f'{folder_path}/Insulin data/bolus_data_1.csv', skiprows=1),
            'basal': pd.read_csv(f'{folder_path}/Insulin data/basal_data_1.csv', skiprows=1)
        }
        logger.info("Successfully processed all data files")
        return data
    except Exception as e:
        logger.error(f"Error processing zip file: {str(e)}")
        raise

@rt("/")
def get():
    form = Form(
        Div(
            H2("Upload Data"),
            Input(type="file", name="file", accept=".zip"),
            cls="upload-section"
        ),
        Div(
            H2("Insulin Pump Settings"),
            generate_settings_table(),
            cls="settings-form"
        ),
        Button("Analyze", type="submit"),
        Div(id="analysis-results", cls="analysis-results"),
        method="POST",
        action="/"  # Post to same URL
    )
    
    return Titled("Insulin Pump Settings Analyzer", form)

@rt("/", methods=["POST"])
async def post(req):  # Make this async
    try:
        form = await req.form()  # Await the form data
        file = form.get('file')
        
        if not file:
            return Div("No file uploaded", cls="error-message")
            
        # Log the analysis request
        logger.info(f"Processing analysis request for file: {file.filename}")
        
        # Create unique folder for this upload
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        folder_path = os.path.join(UPLOAD_FOLDER, timestamp)
        os.makedirs(folder_path, exist_ok=True)
        
        try:
            # Save uploaded file
            file_path = os.path.join(folder_path, file.filename)
            contents = await file.read()  # Await file read
            with open(file_path, 'wb') as f:
                f.write(contents)
            
            # Process data
            data = process_zip_data(file_path, folder_path)
            
            # Collect form data for settings
            settings = []
            for i in range(24):
                settings.append({
                    "time_range": f"{i:02d}:00",
                    "basal_rate": float(form.get(f"basal_rate_{i}", 0)),
                    "correction_factor": form.get(f"correction_factor_{i}", "1:3.0"),
                    "carb_ratio": form.get(f"carb_ratio_{i}", "1:10"),
                    "target_bg": float(form.get(f"target_bg_{i}", 5.6))
                })
            
            # Create user message for LLM
            user_message = f"""
            Current Insulin Pump Settings:
            {json.dumps({"timed_settings": settings}, indent=2)}
            
            Data Analysis:
            {data['alarms'].to_string()}
            {data['cgm'].to_string()}
            {data['bolus'].to_string()}
            {data['basal'].to_string()}
            """
            
            # Log the LLM prompt
            logger.info(f"Sending prompt to LLM:\n{user_message}")
            
            # Get LLM recommendation
            response = completion(
                model="groq/llama-3.1-70b-versatile",
                messages=[
                    {"role": "system", "content": SYSTEM_MESSAGE},
                    {"role": "user", "content": user_message}
                ]
            )
            
            recommendation = response.choices[0].message.content
            
            return Titled("Analysis Results",
                Div(
                    H3("Analysis Results"),
                    Pre(recommendation),
                    A("Back", href="/")
                )
            )
            
        except Exception as e:
            logger.error(f"Error during analysis: {str(e)}")
            return Titled("Error",
                Div(f"An error occurred: {str(e)}", cls="error-message"),
                A("Back", href="/")
            )
        finally:
            # Clean up uploaded files
            if os.path.exists(file_path):
                os.remove(file_path)
                
    except Exception as e:
        logger.error(f"Error processing request: {str(e)}")
        return Titled("Error",
            Div(f"An error occurred: {str(e)}", cls="error-message"),
            A("Back", href="/")
        )

if __name__ == "__main__":
    serve()
