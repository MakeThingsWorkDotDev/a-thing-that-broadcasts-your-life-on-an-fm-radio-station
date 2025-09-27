import os
import json
from pyhtcc import PyHTCC
p = PyHTCC(os.environ['HONEYWELL_USERNAME'], os.environ['HONEYWELL_PASSWORD'])
zone = p.get_zone_by_name('THERMOSTAT')

theromstat_data = {
    "temperature": zone.get_current_temperature_raw(),
    "mode": zone.get_system_mode().name
}

# This is useful if we're calling this from our ruby script
print(json.dumps(theromstat_data))