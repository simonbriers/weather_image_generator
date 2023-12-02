import logging
from homeassistant.core import HomeAssistant
import datetime
import asyncio
import pytz
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE
from geopy.geocoders import Nominatim
import openai
import aiohttp
import os
from .const import DOMAIN
import json



_LOGGER = logging.getLogger(__name__)

async def generate_weather_prompt(hass, entity_id):
    weather_data = hass.states.get(entity_id).attributes # Fetch Met.no weather data
    
def get_season(now):
    month = now.month
    if 3 <= month <= 5:
        return 'Spring'
    elif 6 <= month <= 8:
        return 'Summer'
    elif 9 <= month <= 11:
        return 'Autumn'
    else:
        return 'Winter'

async def async_calculate_day_segment(hass: HomeAssistant) -> str:
    """Calculate the current segment of the day based on sunrise and sunset times."""

    # Internal lookup table for time of day
    day_lookup_table = {
            # ... [your time segments for the day] ...
    }

    # Internal lookup table for time of night
    night_lookup_table = {
            # ... [your time segments for the night] ...
    }
    
    # Internal lookup table for time of day
    day_lookup_table = {
        "0.0-0.1": "sunrise",
        "0.1-0.2": "early morning",
        "0.2-0.3": "mid-morning",
        "0.3-0.4": "late morning",
        "0.4-0.5": "noon",
        "0.5-0.6": "early afternoon",
        "0.6-0.7": "mid-afternoon",
        "0.7-0.8": "late afternoon",
        "0.8-0.9": "dusk",
        "0.9-1.0": "sunset",
        }
    night_lookup_table = {
    "0.0-0.1": "twilight",
    "0.1-0.2": "early night",
    "0.2-0.3": "nightfall",
    "0.3-0.4": "midnight hours",
    "0.4-0.5": "late night",
    "0.5-0.6": "deep night",
    "0.6-0.7": "quiet hours",
    "0.7-0.8": "pre-dawn",
    "0.8-0.9": "dawn's first light",
    "0.9-1.0": "dawn",
    }

    now = datetime.datetime.now(datetime.timezone.utc)
    current_time = now.time()  # Extracting only the time component

    sun_state = hass.states.get('sun.sun').state
    sun_attrs = hass.states.get('sun.sun').attributes
    sunrise_time = datetime.datetime.fromisoformat(sun_attrs['next_rising']).time()
    sunset_time = datetime.datetime.fromisoformat(sun_attrs['next_setting']).time()

    # Calculate the duration of the day
    day_length = datetime.datetime.combine(datetime.date.min, sunset_time) - \
                 datetime.datetime.combine(datetime.date.min, sunrise_time)
    # Calculate the duration of the night
    night_length = datetime.timedelta(hours=24) - day_length

    if sun_state == 'above_horizon':
        # It's daytime
        time_passed = datetime.datetime.combine(datetime.date.min, current_time) - \
                      datetime.datetime.combine(datetime.date.min, sunrise_time)
        period_length = day_length
        lookup_table = day_lookup_table
    else:
        # It's nighttime
        time_passed = datetime.datetime.combine(datetime.date.min, current_time) - \
                      datetime.datetime.combine(datetime.date.min, sunset_time)
        period_length = night_length
        lookup_table = night_lookup_table
    fraction = time_passed.total_seconds() / period_length.total_seconds()

    #_LOGGER.debug(f"Day Length: {day_length}, Night Length: {night_length}, Time Passed: {time_passed}, Fraction of Period Passed: {fraction}")

    # Find the matching description in the lookup table
    for key, description in lookup_table.items():
        if '+' in key:
            lower_bound = key[:-1]
            if fraction >= float(lower_bound):
                return description
        else:
            lower_bound, upper_bound = key.split('-')
            if float(lower_bound) <= fraction < float(upper_bound):
                return description

    return "Unknown time"

async def async_get_weather_conditions(hass: HomeAssistant) -> str:
    # Get the state of the weather entity
    weather_data = hass.states.get('weather.forecast_home')

    if weather_data:
        # Extract required attributes
        temperature = weather_data.attributes.get('temperature')
        cloud_coverage = weather_data.attributes.get('cloud_coverage', 0)  # Default to 0 if not available
        weather_conditions = weather_data.state  # 'sunny' in this case

        # Cloudiness description table
        cloudiness_descriptions = {
            0: "The sky is completely clear.",
            10: "A few wisps of clouds dot the sky.",
            20: "Scattered clouds gently float by.",
            30: "A patchwork of clouds adorns the sky.",
            40: "Partly cloudy with blue sky peeking through.",
            50: "A balanced mix of sun and clouds.",
            60: "More clouds than sun overhead.",
            70: "The sky is mostly cloudy.",
            80: "Thick clouds blanket most of the sky.",
            90: "The sky is grey and heavily clouded.",
            100: "Clouds completely cover the sky.",
        }

        # Find the closest key in the dictionary to the cloud coverage value
        closest_cloudiness = min(cloudiness_descriptions.keys(), key=lambda k: abs(k - cloud_coverage))
        cloudiness_desc = cloudiness_descriptions[closest_cloudiness]

        # Construct your prompt using the weather data
        prompt = f"It's a {weather_conditions} day with a temperature of {temperature}°C. {cloudiness_desc}"

        return prompt
    else:
        _LOGGER.error("Weather data could not be retrieved.")
        return "Weather data could not be retrieved."
    
async def async_create_dalle_prompt(hass: HomeAssistant, chatgpt_in: str, config_data: dict) -> str:
    openai_api_key = config_data.get("openai_api_key")
    chatgpt_model = config_data.get("gpt_model_name", 'gpt-3.5-turbo')
    
    # Check if OpenAI API key is available
    if not openai_api_key:
        _LOGGER.error("OpenAI API key is not configured.")
        return "Error: OpenAI API key is not configured."

    # System instruction for DALL-E prompt creation
    system_instruction = "Create a succinct DALL-E prompt under 100 words, that will create an artistic image, focusing on the most visually striking aspects of the given city/region, weather, and time of day. Highlight key elements that define the scene's character, such as specific landmarks, weather effects, folkore or cultural features, in a direct and vivid manner. Avoid elaborate descriptions; instead, aim for a prompt that vividly captures the essence of the scene in a concise format, suitable for generating a distinct and compelling image."

    def make_api_call():
        openai.api_key = openai_api_key
        return openai.ChatCompletion.create(
            model=chatgpt_model,
            messages=[
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": chatgpt_in}
            ],
            temperature=1,
            max_tokens=256,
            top_p=1,
            frequency_penalty=0,
            presence_penalty=0
        )

    try:
        response = await hass.async_add_executor_job(make_api_call)

        # Check if the response is valid and contains choices
        if response and response.choices and len(response.choices) > 0:
            chatgpt_prompt = response.choices[0].message.content
            return chatgpt_prompt.strip()
    except Exception as e:
        _LOGGER.error(f"Error calling OpenAI API: {e}")
        return f"Error: {str(e)}"

    return "Error: No response from ChatGPT."

async def generate_dalle_image(hass, prompt):
    """Generate an image using DALL-E and return the accessible URL."""
    
    # Retrieve the OpenAI API key and DALL-E model name from the configuration
    config_data = hass.data[DOMAIN]
    openai_api_key = config_data['openai_api_key']
    image_model_name = config_data['image_model_name']

    # Endpoint
    openai_url = "https://api.openai.com/v1/images/generations"
    
    # Headers
    headers = {
        "Authorization": f"Bearer {openai_api_key}",
        "Content-Type": "application/json"
    }
    
    # Payload
    payload = {
        "prompt": prompt,
        "n": 1,
        "model": image_model_name,
        "size": "1024x1024"
    }

    _LOGGER.debug("Payload for DALL-E API: %s", payload)

    # Make the POST request to OpenAI API
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(openai_url, json=payload, headers=headers) as response:
                _LOGGER.debug("Received response status: %s", response.status)
                response_text = await response.text()
                _LOGGER.debug("Received response text: %s", response_text)
                if response.status == 200:
                    result = await response.json()
                    # Check if 'data' is present in the response and it is not empty
                    if 'data' in result and result['data']:
                        # Extract the image URL directly from the data array
                        image_url = result['data'][0].get('url')
                        if image_url:
                            async with session.get(image_url) as image_response:
                                if image_response.status == 200:
                                    image_data = await image_response.read()
                                    try:
                                        with open('/config/www/dalle.png', 'wb') as file:
                                            file.write(image_data)
                                        _LOGGER.debug("Image saved as dalle.png in the directory: %s", os.getcwd())
                                        return image_url  # Return the image URL if saved successfully
                                    except Exception as e:
                                        _LOGGER.error("Error saving the image: %s", str(e))
                                        return None  # Return None if there's an error saving the image
                                else:
                                    _LOGGER.error("Failed to download image: %s", image_response.status)
                                    return None  # Return None if the image download failed
                        else:
                            _LOGGER.error("No 'url' key in the response data.")
                            return None
                    else:
                        _LOGGER.error("The 'data' key is missing or empty in the response.")
                        return None
                else:
                    _LOGGER.error("Failed to generate image with DALL-E: %s", response.status)
                    return None
        except Exception as e:
            _LOGGER.error("Exception occurred while generating image with DALL-E: %s", str(e))
            return None