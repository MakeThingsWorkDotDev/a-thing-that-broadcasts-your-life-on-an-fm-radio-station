# A Thing That Broadcasts Your Life on an FM Radio Station

Companion code for the post at:

https://makethingswork.dev/posts/a-thing-that-broadcasts-your-life-on-an-fm-radio-station

## Setup

Copy `.env.sample` to an `.env` file and enter all the credentials

Copy `wyze_credentials.json.sample` to `wyze_credentials.json`

### Ruby

This was tested with Ruby 3.4.2 on MacOS

```
brew install taglib
env TAGLIB_DIR=/opt/homebrew/Cellar/taglib/2.1.1 gem install taglib-ruby --version '>= 2'
gem install ruby-openai
```

### Python

This was tested with Python 3.9.6

```
pip3 install mutagen openai wyze_sdk pyhtcc
```
