import json
import re

def extract_json_from_string(input_string):
    """
    Extract JSON strings from input string.

    :param input_string: Input string
    :return: List of extracted JSON strings
    """
    json_regex = r'\{[^{}]*\}'
    matches = re.findall(json_regex, input_string)

    valid_jsons = []
    for match in matches:
        try:
            # todo: handle invalid json without ""
            match = match.replace("'", '"')
            json_object = json.loads(match)
            valid_jsons.append(json_object)
        except json.JSONDecodeError:
            continue
    return valid_jsons

def extract_array_from_string(input_string):
    """
    Extract JSON Array from input string.

    :param input_string: Input string
    :return: Extracted JSON Array
    """
    # Use regex to match possible JSON arrays
    start_index = input_string.find('[')
    end_index = input_string.rfind(']') + 1
    json_array_str = input_string[start_index:end_index]
    try:
        json_array = json.loads(json_array_str)
    except json.JSONDecodeError:
        return []
    return json_array

def extract_action_from_string(input_string, actions):
    selected_actions = []
    for name in actions:
        if name in input_string:
            selected_actions.append(name)
    return selected_actions

def parser_text_with_slots(text):
    # Define regex pattern
    pattern = r'\{\{\s*(.*?)\s*\|\s*(.*?)\s*\}\}'
    
    # Find all matching slot names and values
    matches = re.findall(pattern, text)
    
    # Create dictionary of slot names and values
    slots = {slot_name: slot_value for slot_value, slot_name in matches}
    
    # Define replacement function to replace matched parts with slot names
    def replace_with_slot_name(match):
        return match.group(1)
    
    # Replace all {{slot_name | slot_value}} with slot_name in text
    restored_text = re.sub(pattern, replace_with_slot_name, text)
    
    # Return dictionary and restored text
    return slots, restored_text