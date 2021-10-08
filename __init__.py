"""Support to set a timetable (on and off times during the day)."""
from __future__ import annotations

import datetime
import logging

import voluptuous as vol

import homeassistant
from homeassistant.const import (
    ATTR_EDITABLE,
    ATTR_STATE,
    CONF_ID,
    CONF_NAME,
    SERVICE_RELOAD,
    STATE_OFF,
    STATE_ON,
)
from homeassistant.core import CALLBACK_TYPE, callback
from homeassistant.helpers import collection, event as event_helper
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.entity_component import EntityComponent
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.storage import Store
from homeassistant.helpers.typing import ConfigType, HomeAssistantType, ServiceCallType
import homeassistant.util.dt as dt_util

_LOGGER = logging.getLogger(__name__)

DOMAIN = "input_timetable"

ATTR_TIME = "time"
ATTR_TIMETABLE = "timetable"

SERVICE_SET = "set"
SERVICE_UNSET = "unset"
SERVICE_RESET = "reset"
SERVICE_RECONFIG = "reconfig"

MIDNIGHT = datetime.time()


class StateEvent:
    """State event properties (time, and state value)."""

    def __init__(self, time: datetime.time, state: str) -> None:
        """Initialize the object."""
        self.time = time
        self.state = state


def remove_micros_and_tz(time: datetime.time) -> datetime.time:
    """Remove microseconds and timezone from a time object."""
    return time.replace(microsecond=0, tzinfo=None)


CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: cv.schema_with_slug_keys(
            vol.Any(
                {
                    vol.Optional(CONF_NAME): cv.string,
                },
                None,
            )
        )
    },
    extra=vol.ALLOW_EXTRA,
)

SERVICE_SET_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_TIME): vol.All(cv.time, remove_micros_and_tz),
        vol.Required(ATTR_STATE): vol.In([STATE_ON, STATE_OFF]),
    },
    extra=vol.ALLOW_EXTRA,
)
SERVICE_UNSET_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_TIME): vol.All(cv.time, remove_micros_and_tz),
    },
    extra=vol.ALLOW_EXTRA,
)
SERVICE_RESET_SCHEMA = vol.Schema(
    {},
    extra=vol.ALLOW_EXTRA,
)
SERVICE_RECONFIG_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_TIMETABLE): vol.All(cv.ensure_list, [SERVICE_SET_SCHEMA]),
    },
    extra=vol.ALLOW_EXTRA,
)
RELOAD_SERVICE_SCHEMA = vol.Schema({})

STORAGE_KEY = DOMAIN
STORAGE_VERSION = 1

CREATE_FIELDS = {
    vol.Required(CONF_NAME): vol.All(str, vol.Length(min=1)),
}

UPDATE_FIELDS = {
    vol.Optional(CONF_NAME): cv.string,
}


async def async_setup(hass: HomeAssistantType, config: ConfigType) -> bool:
    """Set up an input timetable."""
    component = EntityComponent(_LOGGER, DOMAIN, hass)
    id_manager = collection.IDManager()

    yaml_collection = collection.YamlCollection(
        logging.getLogger(f"{__name__}.yaml_collection"), id_manager
    )
    collection.sync_entity_lifecycle(
        hass, DOMAIN, DOMAIN, component, yaml_collection, InputTimeTable.from_yaml
    )

    storage_collection = TimeTableStorageCollection(
        Store(hass, STORAGE_VERSION, STORAGE_KEY),
        logging.getLogger(f"{__name__}.storage_collection"),
        id_manager,
    )
    collection.sync_entity_lifecycle(
        hass, DOMAIN, DOMAIN, component, storage_collection, InputTimeTable
    )

    await yaml_collection.async_load(
        [{CONF_ID: id_, **(conf or {})} for id_, conf in config.get(DOMAIN, {}).items()]
    )
    await storage_collection.async_load()

    collection.StorageCollectionWebsocket(
        storage_collection, DOMAIN, DOMAIN, CREATE_FIELDS, UPDATE_FIELDS
    ).async_setup(hass)

    component.async_register_entity_service(
        SERVICE_SET, SERVICE_SET_SCHEMA, "async_set"
    )
    component.async_register_entity_service(
        SERVICE_UNSET, SERVICE_UNSET_SCHEMA, "async_unset"
    )
    component.async_register_entity_service(
        SERVICE_RESET, SERVICE_RESET_SCHEMA, "async_reset"
    )
    component.async_register_entity_service(
        SERVICE_RECONFIG, SERVICE_RECONFIG_SCHEMA, "async_reconfig"
    )

    async def reload_service_handler(service_call: ServiceCallType) -> None:
        """Reload yaml entities."""
        conf = await component.async_prepare_reload(skip_reset=True)
        conf = conf or {}
        await yaml_collection.async_load(
            [
                {CONF_ID: entity_id, **(entity_conf or {})}
                for entity_id, entity_conf in conf.get(DOMAIN, {}).items()
            ]
        )

    homeassistant.helpers.service.async_register_admin_service(
        hass,
        DOMAIN,
        SERVICE_RELOAD,
        reload_service_handler,
        schema=RELOAD_SERVICE_SCHEMA,
    )

    return True


class TimeTableStorageCollection(collection.StorageCollection):
    """Input storage based collection."""

    CREATE_SCHEMA = vol.Schema(CREATE_FIELDS)
    UPDATE_SCHEMA = vol.Schema(UPDATE_FIELDS)

    async def _process_create_data(self, data: dict) -> dict:
        """Validate the config is valid."""
        return self.CREATE_SCHEMA(data)

    @callback
    def _get_suggested_id(self, info: dict) -> str:
        """Suggest an ID based on the config."""
        return info[CONF_NAME]

    async def _update_data(self, data: dict, update_data: dict) -> dict:
        """Return a new updated data object."""
        self.UPDATE_SCHEMA(update_data)
        return {**data, **update_data}


class InputTimeTable(RestoreEntity):
    """Representation of a timetable."""

    def __init__(self, config: dict) -> None:
        """Initialize an input timetable."""
        self._config: dict = config
        self._timetable: list[StateEvent] = []
        self.editable = True
        self._event_unsub: CALLBACK_TYPE | None = None

    @classmethod
    def from_yaml(cls, config: dict) -> InputTimeTable:
        """Return entity instance initialized from yaml storage."""
        input_timetable = cls(config)
        input_timetable.entity_id = f"{DOMAIN}.{config[CONF_ID]}"
        input_timetable.editable = False
        return input_timetable

    @property
    def should_poll(self) -> bool:
        """No polling needed."""
        return False

    @property
    def name(self):
        """Return the name of the input timetable."""
        return self._config.get(CONF_NAME)

    @property
    def state(self) -> str:
        """Return the state based on the timetable events."""
        if not self._timetable:
            return STATE_OFF
        now = dt_util.now().time()
        prev = StateEvent(MIDNIGHT, self._timetable[-1].state)
        for event in self._timetable:
            if prev.time <= now < event.time:
                break
            prev = event
        return prev.state

    @property
    def state_attributes(self) -> dict:
        """Return the state attributes."""
        return {
            ATTR_EDITABLE: self.editable,
            ATTR_TIMETABLE: self._timetable_to_attribute(),
        }

    @property
    def unique_id(self) -> str | None:
        """Return unique id of the entity."""
        return self._config[CONF_ID]

    async def async_added_to_hass(self) -> None:
        """Run when entity about to be added to hass."""
        await super().async_added_to_hass()
        state = await self.async_get_last_state()
        if state and state.attributes.get(ATTR_TIMETABLE):
            self._timetable_from_attribute(state.attributes[ATTR_TIMETABLE])
        self._update_state()

    def _timetable_to_attribute(self) -> list:
        return [
            {ATTR_TIME: event.time.isoformat(), ATTR_STATE: event.state}
            for event in self._timetable
        ]

    def _timetable_from_attribute(self, timetable: list) -> None:
        self._timetable = [
            StateEvent(
                datetime.time.fromisoformat(event[ATTR_TIME]),
                event[ATTR_STATE],
            )
            for event in timetable
        ]
        self._sort_timetable()

    def _sort_timetable(self) -> None:
        self._timetable.sort(key=lambda event: event.time)

    async def async_set(self, time: datetime.time, state: str) -> None:
        """Add a state change event to the timetable."""
        for event in self._timetable:
            if event.time == time:
                event.state = state
                break
        else:
            self._timetable.append(StateEvent(time, state))
            self._sort_timetable()
        self._update_state()

    async def async_unset(self, time: datetime.time) -> None:
        """Remove a state change event."""
        for event in self._timetable:
            if event.time == time:
                self._timetable.remove(event)
                break
        else:
            raise vol.Invalid(f"The time {time.isoformat()} doesn't exist")
        self._update_state()

    async def async_reset(self) -> None:
        """Remove all state changes."""
        self._timetable.clear()
        self._update_state()

    async def async_reconfig(self, timetable: list) -> None:
        """Override the timetable with the new list."""
        if len(timetable) > len({event[ATTR_TIME] for event in timetable}):
            raise vol.Invalid("The same time is not allowed more than once")
        self._timetable = [
            StateEvent(event[ATTR_TIME], event[ATTR_STATE]) for event in timetable
        ]
        self._sort_timetable()
        self._update_state()

    async def async_update_config(self, config: dict) -> None:
        """Handle when the config is updated."""
        self._config = config
        self._update_state()

    def _schedule_update(self) -> None:
        if self._event_unsub:
            self._event_unsub()
            self._event_unsub = None

        if not self._timetable or len(self._timetable) == 1:
            return

        now = dt_util.now()
        time = now.time()
        today = now.date()
        prev = MIDNIGHT
        for event in self._timetable:
            if prev <= time < event.time:
                next_change = datetime.datetime.combine(
                    today,
                    event.time,
                )
                break
            prev = event.time
        else:
            next_change = datetime.datetime.combine(
                today + datetime.timedelta(days=1),
                self._timetable[0].time,
            )

        self._event_unsub = event_helper.async_track_point_in_time(
            self.hass, self._update_state, next_change
        )

    @callback
    def _update_state(self, *_):
        """Update the state to reflect the current time."""
        self._schedule_update()
        self.async_write_ha_state()
