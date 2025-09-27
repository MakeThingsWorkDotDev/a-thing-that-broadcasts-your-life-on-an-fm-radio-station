require 'json'
require 'net/http'
require 'uri'
require 'taglib'
require 'net/imap'
require 'openai'
require 'time'

class Broadcast < Struct.new(:created_at, :events, :script_prompt, :script, :audio_file, :error)
  FILE_PATH = 'broadcast.json'

  def initialize(created_at: '', events: [], script_prompt: '', script: '', audio_file: '', error: '')
    super(created_at, events, script_prompt, script, audio_file, error)
  end

  def self.load
    return new unless File.exist?(FILE_PATH)

    data = JSON.parse(File.read(FILE_PATH))
    new(**data.transform_keys(&:to_sym))
  rescue JSON::ParserError
    new
  end

  def save
    File.write(FILE_PATH, JSON.pretty_generate(to_h))
    self
  end

  def to_h
    super.transform_keys(&:to_s)
  end
end

def ordinalize(number)
  abs_number = number.to_i.abs
  
  if (11..13).include?(abs_number % 100)
    "#{number}th"
  else
    case abs_number % 10
    when 1 then "#{number}st"
    when 2 then "#{number}nd"
    when 3 then "#{number}rd"
    else "#{number}th"
    end
  end
end

def get_weather_event
  uri = URI('https://api.openweathermap.org/data/3.0/onecall')
  uri.query = URI.encode_www_form({
    lat: ENV['LATITUDE'],
    lon: ENV['LONGITUDE'],
    appid: ENV['OPENWEATHERMAP_API_KEY'],
    units: 'imperial',
    exclude: 'minutely,hourly' # we only want daily forecasts
  })

  response = Net::HTTP.get_response(uri)
  weather_data = response.code == '200' ? JSON.parse(response.body) : nil

  current = weather_data["current"]
  today = weather_data["daily"][0]
  tomorrow = weather_data["daily"][1]
  right_now = Time.at(current['dt'])

  [
    'Today,',
    right_now.strftime("%A, %B the #{ordinalize(right_now.day)}"),
    "#{today['summary']}.",
    "Right now it's #{current['temp'].round} and feels like #{current['feels_like'].round}",
    "with a low of #{today['temp']['min'].round}",
    "with a high of #{today['temp']['max'].round}.",
    "Tomorrow, #{tomorrow['summary']}",
    "and a high of #{tomorrow['temp']['max'].round} and a heat index of #{tomorrow['feels_like']['day'].round}"
   ].join(' ')
end

def get_email_events
  imap = Net::IMAP.new(ENV['IMAP_HOST'], '993', true, nil, false)
  imap.authenticate('LOGIN', ENV['IMAP_USERNAME'], ENV['IMAP_PASSWORD'])
  imap.select('INBOX')

  search_terms = ["Shipped", "Out for Delivery", "Delivered", "on its way", "shipped", "on the way"]

  # IMAP querying is weird in ruby. You have to submit an array that
  # first contains your verbs, then you put in a field and search criteria
  # for each verb. So if I wanted to search a subject for "Amazon" OR "Walmart"
  # The array would be formatted as ["OR", "SUBJECT", "Amazon", "SUBJECT", "Walmart"]
  # weird, huh? The code below handles that.

  search_array = []
  # we need one OR for each pair of "FIELD" and "SEARCH TERMS", minus one because
  # we don't want a trailing "or"
  ((search_terms.count * 2) - 1).times { search_array << 'OR' }
  search_terms.each { |term| search_array += ['SUBJECT', term, 'SUBJECT', term.downcase] }
  email_seq_nos = imap.search(search_array)
  emails = if email_seq_nos == []
             []
           else
             imap.fetch(email_seq_nos, %w[ENVELOPE UID])
           end
  return [] if emails.count < 1

  puts "SHAZOOOM"

  emails.map do |email|
    puts email.attr['ENVELOPE'].date
    [
      "An email from #{email.attr['ENVELOPE'].from.first.name}",
      "with a subject of '#{email.attr['ENVELOPE'].subject.gsub(/\p{Emoji_Presentation}/, '').strip}'",
      "was received at #{email.attr['ENVELOPE'].date.strftime('%D %I:%M:%S %p')}"
    ].join(' ')
  end
end

def get_camera_events
  events = JSON.parse(`python3 get_wyze_events.py`)
  events.map do |event|
    event_time = DateTime.strptime(event['time'].to_s, '%Q').to_time.localtime
    event_text = "#{event['camera_name']} detected #{event['alarm_type']}"
    if event['tags'].count.positive?
      verb = event['alarm_type'].downcase == 'sound' ? 'heard' : 'saw'
      event_text = "#{event_text} and #{verb} #{event['tags'].map { |t| "a #{t}" }.join(' and ')}"
    end
    event_text   
  end
end

def get_thermostat_status
  status = JSON.parse(`python3 get_honeywell_status.py`)
  "The thermostat is set to #{status['mode']} and the indoor temperature is #{status['temperature']}"
end

def base_script_prompt
  <<-PROMPT.freeze
    In the style of a 1930's radio broadcaster, give a news update summarizing the below events.
    Do not include prompts, headers, or asterisks in the output.
    Do not read them all individually but group common events and summarize them.
    Do not include sound or music prompts. Mention that the broadcast is for the current time of #{Time.now.strftime('%I:00 %p')}
    The news update should be verbose and loquacious but please do not refer to yourself as either.
    The station name is 1.101 Cozy Castle Radio and your radio broadcaster name is Hotsy Totsy Harry Fitzgerald.
    At some point in the broadcast advertise for a ridiculous fictional product from the 1930's or tell a joke, do not do both.
    Give an introduction to the news report and a sign off.
    Here are the events:
  PROMPT
end

def generate_script(script_prompt)
  openai_client = OpenAI::Client.new(
    access_token: ENV['OPENAI_ACCESS_TOKEN'],
    organization_id: ENV['OPENAI_ORGANIZATION_ID']
  )

  messages = [{ role: 'user', content: script_prompt }]
  response = openai_client.chat(parameters: { model: 'gpt-5', messages: })
  response.dig('choices', 0, 'message', 'content')
end

def get_script_audio(text, filename)
  uri = URI("https://api.elevenlabs.io/v1/text-to-speech/#{ENV['ELEVENLABS_VOICE_ID']}/stream")
  http = Net::HTTP.new(uri.host, uri.port)
  http.use_ssl = true

  request = Net::HTTP::Post.new(uri)

  headers = {
    'xi-api-key' => ENV['ELEVENLABS_API_KEY'],
    'Content-Type' => 'application/json',
    'Accept' => 'audio/mpeg'
  }

  headers.each { |key, value| request[key] = value }
  request.body = { text: text, model_id: 'eleven_monolingual_v1' }.to_json

  File.open(filename, 'wb') do |file|
    http.request(request) do |response|
      raise StandardError, "Non-success status code while streaming #{response.code}" unless response.code == '200'

      response.read_body do |chunk|
        file.write(chunk)
      end
    end
  end

  filename
end

# Uses the library tool to read length in seconds from mp3 files
# brew install taglib
# env TAGLIB_DIR=/opt/homebrew/Cellar/taglib/2.1.1 gem install taglib-ruby --version '>= 2'
def audio_length_in_seconds(file_path)
  length = 0
  return length unless File.exist?(file_path)

  TagLib::MPEG::File.open(file_path) do |file|
    length = file.audio_properties.length_in_seconds
  end
  length
end

def mix_broadcast_audio(vocals_file, output_file)
    original_intro_outro_file = "radio_intro_outro.mp3"
    vocals_length = audio_length_in_seconds(vocals_file)
    intro_outro_length = audio_length_in_seconds(original_intro_outro_file)

    working_dir = 'work'
    intro_outro_file = "#{working_dir}/radio_intro_outro_resampled.mp3"
    padded_vocals_file = "#{working_dir}/padded_vocals.mp3".freeze
    faded_intro_outro_file = "#{working_dir}/faded_intro_outro.mp3"
    padded_outro_file = "#{working_dir}/padded_outro.mp3".freeze
    mixed_broadcast_file = "#{working_dir}/mixed_broadcast.wav".freeze
    compressed_broadcast_file = "#{working_dir}/compressed_broadcast.wav".freeze

    # create work directory and clear old file file
    system("mkdir work")
    system("rm #{output_file}")

    # resample file from Udio
    system("sox #{original_intro_outro_file} #{intro_outro_file} rate -h 44100")

    # pad vocals
    system("sox #{vocals_file} #{padded_vocals_file} pad 10@0")
    # fade intro outro
    system("sox #{intro_outro_file} #{faded_intro_outro_file} fade 5 25 20")
    # pad outro
    system("sox #{faded_intro_outro_file} #{padded_outro_file} pad #{vocals_length}@0")
    # mix files
    system("sox -M -v 0.3 #{faded_intro_outro_file} -v 1.2 #{padded_vocals_file} -v 0.4 #{padded_outro_file} #{mixed_broadcast_file}")
    # compress and fade in
    system("sox #{mixed_broadcast_file} #{compressed_broadcast_file} fade 5 compand 0.3,1 6:-70,-60,-20 -5 -90 0.2 norm -3")
    # rubocop:enable Layout/LineLength

    # wav to mono mp3
    system("sox #{compressed_broadcast_file} #{output_file} remix -")

    # cleanup everything
    system("rm -rf work")
    system("rm vocals_file.mp3")

    output_file
end

start_time = Time.now
puts "Starting Broadcast Generation... 🎙️"

record = Broadcast.load

record.created_at = Time.now.to_s

puts "Collecting Weather Data ☀️"
record.events << get_weather_event

puts "Collecting Email Events 📧"
record.events += get_email_events

puts "Collecting Camera Events 📹"
record.events += get_camera_events

puts "Collecting Thermostat Status 🌡️"
record.events << get_thermostat_status

record.script_prompt = "#{base_script_prompt} #{record.events.join("\n")}"

puts "Generating Script ✍️"
record.script = generate_script(record.script_prompt)

puts "Getting Vocals 🎤"
vocals_file = get_script_audio(record.script, "vocals_file.mp3")

puts "Mixing Audio 🎵"
record.audio_file = mix_broadcast_audio(vocals_file, "broadcast.mp3")

record.save

end_time = Time.now
elapsed_time = (end_time - start_time).round(2)
puts "You're done! 🎉 (Completed in #{elapsed_time} seconds)"