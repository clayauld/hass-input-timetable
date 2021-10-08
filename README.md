# Note: THIS IS NOT WORKING PROPERLY YET!!!

# Installation instructions:

Simply clone the repo to the /config/custom_components directory in Home Assistant. Then run the following:

```bash
cd hass-input-timetable
cp ./timetable-card.js ../../www/timetable-card.js
```
This will put the timetable-card.js file at /config/www/timetable-card.js.

You will need to register this card on the Resources screen. Follow instructions [here](https://developers.home-assistant.io/docs/frontend/custom-ui/registering-resources) and use the following info:

```
/local/timetable-card.js
```

Add the card to the UI by following this sample:

```
type: custom:timetable-card
title: Timers
toggle: input_boolean.timers
entities:
  - entity: input_timetable.timer1
    name: light1
  - entity: input_timetable.timer2
    name: light2
```



# Credits
## Notes from the Pull Request: https://github.com/home-assistant/core/pull/41385#issuecomment-938909888

@MarkusHornbach, thanks!
Yes, you can use it as a custom component. All you need to do is to copy the files in the PR under homeassistant/components/input_timetable on to HA at /config/custom_components/input_timetable (and restart HA).
In addition, you need to use a custom card, which I created as an interim solution, found at https://github.com/amitfin/Home-Assistant-Config/blob/master/www/timetable-card.js . It should be placed in the same path (/config/www/timetable-card.js). Follow the instruction at https://developers.home-assistant.io/docs/frontend/custom-ui/registering-resources to register it.
A sample card will look like this:

title: Timers
toggle: input_boolean.timers
entities:
  - entity: input_timetable.timer1
    name: light1
  - entity: input_timetable.timer2
    name: light2

I've been using this interim solution for months (while waiting for someone to review this component, please?)

# Proposed change

This is a new integration which should help using fixed automation rules, while controlling their behavior through this new entity type.
The "input_timetable" entity has an on/off state based on the time periods provided as input by the user. It preserves the time periods during reboots.
A typical usage will be to create a static automation rule, which will behave according to changes in the time periods of the timetable, without the need to change the rule itself.
A demo clip can be found here: https://www.youtube.com/watch?v=TluMAZpORwk.