"""Repair issues for Music Assistant players with no room, and for names two players share."""

from datetime import timedelta

from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.thalovant.const import DOMAIN, PLAYER_CHECK_DELAY
from custom_components.thalovant.rooms import (
    ENTITIES_URL,
    PlayerChecker,
    async_delete_entry_issues,
    clash_issue_id,
    name_clash,
    no_area_issue_id,
)
from homeassistant.components.homeassistant.exposed_entities import async_expose_entity
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
    entity_registry as er,
    issue_registry as ir,
)
from homeassistant.util import dt as dt_util

from .conftest import FakeHubConnection
from .test_music import MA_DOMAIN, Fake, _house


async def _settle(hass: HomeAssistant) -> None:
    """Let the delayed look at the players happen."""
    async_fire_time_changed(
        hass, dt_util.utcnow() + timedelta(seconds=PLAYER_CHECK_DELAY + 1)
    )
    await hass.async_block_till_done()


def _issue(hass: HomeAssistant, issue_id: str) -> ir.IssueEntry | None:
    return ir.async_get(hass).async_get_issue(DOMAIN, issue_id)


async def _started(
    hass: HomeAssistant, entry: MockConfigEntry
) -> tuple[Fake, PlayerChecker]:
    fake = await _house(hass)
    checker = PlayerChecker(hass, entry)
    entry.async_on_unload(checker.async_start())
    await hass.async_block_till_done()
    return fake, checker


async def test_a_player_with_no_room_raises_a_repair_issue(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Only an exposed Music Assistant player with no area; the issue is a plain warning."""
    fake, _ = await _started(hass, mock_config_entry)
    entry_id = mock_config_entry.entry_id
    issue = _issue(hass, no_area_issue_id(entry_id, fake.ids["Mark2"]))
    assert issue is not None
    assert issue.severity is ir.IssueSeverity.WARNING
    assert issue.is_fixable is False
    assert issue.translation_key == "music_player_no_area"
    assert issue.translation_placeholders == {
        "player": "Mark2",
        "device_url": ENTITIES_URL,
    }
    # a player that has a room, one that is not exposed and a Chromecast are never reported
    for name in ("Kitchen", "Bedroom"):
        assert _issue(hass, no_area_issue_id(entry_id, fake.ids[name])) is None
    assert _issue(hass, no_area_issue_id(entry_id, "media_player.hidden")) is None
    assert _issue(hass, no_area_issue_id(entry_id, "media_player.kitchen_cast")) is None


async def test_the_issue_links_to_the_device_and_clears_with_its_room(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """A room given to the device clears it, after the registry update settles."""
    fake = await _house(hass)
    ents, devs = er.async_get(hass), dr.async_get(hass)
    ma = hass.config_entries.async_entries(MA_DOMAIN)[0]
    device = devs.async_get_or_create(
        config_entry_id=ma.entry_id, identifiers={(MA_DOMAIN, "mark2")}, name="Mark2"
    )
    ents.async_update_entity(fake.ids["Mark2"], device_id=device.id)
    checker = PlayerChecker(hass, mock_config_entry)
    mock_config_entry.async_on_unload(checker.async_start())
    await hass.async_block_till_done()

    issue_id = no_area_issue_id(mock_config_entry.entry_id, fake.ids["Mark2"])
    issue = _issue(hass, issue_id)
    assert issue is not None
    assert issue.translation_placeholders is not None
    assert issue.translation_placeholders["device_url"] == (
        f"/config/devices/device/{device.id}"
    )

    # two changes in a burst are looked at once, after the delay
    area = ar.async_get(hass).async_create("Study")
    devs.async_update_device(device.id, name_by_user="Mark 2")
    devs.async_update_device(device.id, area_id=area.id)
    await hass.async_block_till_done()
    assert _issue(hass, issue_id) is not None  # not looked at yet
    await _settle(hass)
    assert _issue(hass, issue_id) is None


async def test_a_room_on_the_entity_clears_the_issue_and_a_new_player_raises_one(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """The entity's own area counts, and a player that appears later is noticed."""
    fake, _ = await _started(hass, mock_config_entry)
    ents = er.async_get(hass)
    issue_id = no_area_issue_id(mock_config_entry.entry_id, fake.ids["Mark2"])
    ents.async_update_entity(
        fake.ids["Mark2"], area_id=ar.async_get(hass).async_create("Study").id
    )
    await _settle(hass)
    assert _issue(hass, issue_id) is None

    ma = hass.config_entries.async_entries(MA_DOMAIN)[0]
    new = ents.async_get_or_create(
        "media_player",
        MA_DOMAIN,
        "ma-porch",
        suggested_object_id="porch",
        config_entry=ma,
    )
    hass.states.async_set(new.entity_id, "idle", {"friendly_name": "Porch"})
    async_expose_entity(hass, "conversation", new.entity_id, True)
    await _settle(hass)
    assert _issue(hass, no_area_issue_id(mock_config_entry.entry_id, new.entity_id))


async def test_two_players_with_one_name_raise_a_repair_issue_until_one_is_renamed(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """A Chromecast called Kitchen and the Music Assistant Kitchen."""
    fake, _ = await _started(hass, mock_config_entry)
    issue_id = clash_issue_id(mock_config_entry.entry_id, "Kitchen")
    issue = _issue(hass, issue_id)
    assert issue is not None
    assert issue.severity is ir.IssueSeverity.WARNING
    assert issue.is_fixable is False
    assert issue.translation_key == "music_name_clash"
    assert issue.translation_placeholders == {
        "name": "Kitchen",
        "other_url": ENTITIES_URL,
    }

    cast = er.async_get(hass).async_get("media_player.kitchen_cast")
    assert cast is not None
    hass.states.async_set(cast.entity_id, "idle", {"friendly_name": "Lounge TV"})
    er.async_get(hass).async_update_entity(cast.entity_id, name="Lounge TV")
    await _settle(hass)
    assert _issue(hass, issue_id) is None
    # the unrelated room issue is still there
    assert _issue(hass, no_area_issue_id(mock_config_entry.entry_id, fake.ids["Mark2"]))


async def test_an_alias_counts_as_a_spoken_name(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Assist says an alias as it says a name."""
    fake, _ = await _started(hass, mock_config_entry)
    er.async_get(hass).async_update_entity(fake.ids["Bedroom"], aliases={"Lounge TV"})
    cast = er.async_get(hass).async_get("media_player.kitchen_cast")
    assert cast is not None
    er.async_get(hass).async_update_entity(cast.entity_id, aliases={"lounge tv"})
    await _settle(hass)
    assert _issue(hass, clash_issue_id(mock_config_entry.entry_id, "Lounge TV"))


async def test_name_clash_names_the_other_players(hass: HomeAssistant) -> None:
    """Only a name the player answers to, and only another exposed media player."""
    fake = await _house(hass)
    player = hass.states.get(fake.ids["Kitchen"])
    assert player is not None
    assert [s.entity_id for s in name_clash(hass, player, "the Kitchen!")] == []
    assert [s.entity_id for s in name_clash(hass, player, "Kitchen")] == [
        "media_player.kitchen_cast"
    ]
    assert name_clash(hass, player, "Bedroom") == []
    assert name_clash(hass, player, "") == []


async def test_a_name_only_one_player_has_is_not_reported(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """A clash needs another exposed media player, so the Chromecast leaving ends it."""
    fake = await _house(hass)
    # the Chromecast leaves: nothing else answers to Kitchen
    hass.states.async_remove("media_player.kitchen_cast")
    checker = PlayerChecker(hass, mock_config_entry)
    mock_config_entry.async_on_unload(checker.async_start())
    await hass.async_block_till_done()
    assert _issue(hass, clash_issue_id(mock_config_entry.entry_id, "Kitchen")) is None
    assert fake.ids["Kitchen"]


async def test_the_entry_clears_its_issues_on_unload_and_removal(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_hub_connection: FakeHubConnection,
) -> None:
    """Set up through the integration; unloading keeps nothing, and a stale issue goes on removal."""
    fake = await _house(hass)
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.LOADED
    entry_id = mock_config_entry.entry_id
    assert _issue(hass, no_area_issue_id(entry_id, fake.ids["Mark2"]))
    assert _issue(hass, clash_issue_id(entry_id, "Kitchen"))

    await hass.config_entries.async_unload(entry_id)
    await hass.async_block_till_done()
    assert _issue(hass, no_area_issue_id(entry_id, fake.ids["Mark2"])) is None
    assert _issue(hass, clash_issue_id(entry_id, "Kitchen")) is None

    # an issue left from before a restart is found by its prefix, and only this entry's
    for key, name in ((entry_id, "a"), ("other-entry", "b")):
        ir.async_create_issue(
            hass,
            DOMAIN,
            no_area_issue_id(key, f"media_player.{name}"),
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="music_player_no_area",
        )
    await hass.config_entries.async_remove(entry_id)
    assert _issue(hass, no_area_issue_id(entry_id, "media_player.a")) is None
    assert _issue(hass, no_area_issue_id("other-entry", "media_player.b")) is not None
    async_delete_entry_issues(hass, "other-entry")
    assert _issue(hass, no_area_issue_id("other-entry", "media_player.b")) is None


async def test_unloading_before_the_delay_cancels_the_look(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """A change just before unload leaves no timer behind."""
    await _house(hass)
    checker = PlayerChecker(hass, mock_config_entry)
    stop = checker.async_start()
    await hass.async_block_till_done()
    er.async_get(hass).async_update_entity("media_player.kitchen_cast", name="Cast")
    await hass.async_block_till_done()
    stop()
    checker.async_clear()
    await _settle(hass)
    assert _issue(hass, clash_issue_id(mock_config_entry.entry_id, "Kitchen")) is None
