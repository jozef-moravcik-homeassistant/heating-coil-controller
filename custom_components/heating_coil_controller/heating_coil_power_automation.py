from __future__ import annotations
"""The Heating Coil Controller"""
"""Author: Jozef Moravcik"""
"""email: jozef.moravcik@moravcik.eu"""

""" heating_coil_power_automation.py """

"""Modul pre automatické riadenie výkonu špirál na základe externých senzorov."""

import time
import logging

from .const import (
    POWER_CONTROL_STRATEGY_MANUAL,
    POWER_CONTROL_STRATEGY_1,
    POWER_CONTROL_STRATEGY_2,
    POWER_CONTROL_STRATEGY_SOLAR_SENSOR,
    POWER_CONTROL_STRATEGY_PV_POWER,
    POWER_CONTROL_STRATEGY_POWER_GRID,
    POWER_CONTROL_STRATEGY_BATTERY,
)

LOGGER = logging.getLogger(__name__)


class HeatingCoilPowerAutomation:
    """Trieda pre automatické riadenie výstupného výkonu špirály.

    Metóda power_automation() vracia hodnotu 0–100 (int), ktorá sa aplikuje
    na self.max_power v controlleri ako multiplikátor:
        effective_max_power = (max_power * power_automation_output) / 100
    """

    def __init__(self) -> None:
        # Aktuálny výstupný výkon automatizácie (0.0 – 100.0)
        self._current_output: float = 0.0

        # Časové značky posledného kroku rampy pre jednotlivé zdroje
        self._solar_last_ramp_time: float = 0.0
        self._pv_last_ramp_time: float = 0.0
        self._power_grid_last_ramp_time: float = 0.0
        self._battery_last_ramp_time: float = 0.0



        # Strategy 1 – vlastné predchádzajúce hodnoty pre detekciu rýchlych zmien
        self._prev_battery_power_s1: float | None = None
        self._prev_power_grid_value_s1: float | None = None

        # Indikátor aktívnej rampy a čas do ďalšieho kroku
        self._ramp_active: bool = False
        self._next_ramp_delay: float = 0.0

    @property
    def ramp_active(self) -> bool:
        """Vráti True ak je rampa aktívna (current != target)."""
        return self._ramp_active

    @property
    def next_ramp_delay(self) -> float:
        """Vráti čas v sekundách do ďalšieho kroku rampy."""
        return self._next_ramp_delay

    @property
    def current_output(self) -> float:
        """Vráti aktuálnu internú hodnotu výstupu automatizácie."""
        return self._current_output

    def sync_output(self, actual_output: float) -> None:
        """Synchronizuje interný _current_output na skutočný výstupný výkon.

        Volané po aplikácii total power limitu, aby rampa pri ďalšom
        cykle krokovala od skutočného výstupného výkonu, nie od internej
        hodnoty ktorá mohla byť orezaná limitom.

        Args:
            actual_output: skutočný výstupný výkon (0-100 %) po všetkých limitoch
        """
        if abs(self._current_output - actual_output) > 0.01:
            LOGGER.debug(
                "PowerAutomation sync: internal %.1f%% → actual %.1f%%",
                self._current_output, actual_output,
            )
            self._current_output = actual_output

    def reset(self) -> None:
        """Reset interného stavu automatizácie na východiskové hodnoty."""
        self._current_output = 0.0
        self._solar_last_ramp_time = 0.0
        self._pv_last_ramp_time = 0.0
        self._power_grid_last_ramp_time = 0.0
        self._battery_last_ramp_time = 0.0
        self._prev_battery_power_s1 = None
        self._prev_power_grid_value_s1 = None
        self._ramp_active = False
        self._next_ramp_delay = 0.0

    def power_automation(self, settings) -> int:
        """Hlavná metóda automatického riadenia výkonu.

        Podľa zvolenej stratégie (power_control_strategy) riadi výstupný výkon.
        Podľa zvolenej stratégie sa vyberá zdroj riadenia výkonu.

        Args:
            settings: objekt Settings z Heating_Coil_Controller_Instance
                      obsahujúci všetky konfiguračné a runtime premenné.

        Returns:
            int: výstupný výkon automatizácie v rozsahu 0–100.
        """
        strategy = settings.power_control_strategy
        self._ramp_active = False
        self._next_ramp_delay = 0.0

        # ---------------------------------------------------------------
        # MANUAL – manuálne ovládanie
        # ---------------------------------------------------------------
        if strategy == POWER_CONTROL_STRATEGY_MANUAL:
            return 100

        # ---------------------------------------------------------------
        # Strategy 1 – synchrónne riadenie výkonu podľa 4 scenárov
        # Rytmus dáva tracked_entities_interval (bez asynchrónnych timerov).
        # Scenáre sa určujú podľa kombinácie EXPORT, POVOLENÉ NABÍJANIE a SOC.
        # Batéria má vždy vyššiu prioritu než grid.
        #
        # Scenár 1: EXPORT=OFF, NABÍJANIE=ON, SOC<100 → len batéria
        # Scenár 2: EXPORT=ON,  NABÍJANIE=ON, SOC<100 → batéria + grid (export→UP, import ignorovaný)
        # Scenár 3: EXPORT=OFF, NABÍJANIE=OFF/SOC=100 → batéria(DOWN) + grid(import→DOWN) + probing
        # Scenár 4: EXPORT=ON,  NABÍJANIE=OFF/SOC=100 → batéria(DOWN) + grid(oba smery)
        # ---------------------------------------------------------------
        if strategy == POWER_CONTROL_STRATEGY_1:

            if not settings.strategy_1_grid_export_status_entity_available:
                return 100
            if not settings.strategy_1_battery_power_entity_available:
                return 100
            if not settings.strategy_1_power_grid_entity_available:
                return 100
            if not settings.strategy_1_battery_charging_enablement_state_available:
                return 100
            if not settings.strategy_1_battery_state_of_charge_available:
                return 100

            # Čítanie hodnôt
            grid_export_status = settings.strategy_1_grid_export_status_value
            battery_charging_enabled = settings.strategy_1_battery_charging_enablement_state_value
            battery_soc = settings.strategy_1_battery_state_of_charge_value

            battery_power = settings.strategy_1_battery_power_value_w
            battery_dead_zone = settings.strategy_1_battery_power_dead_zone_w
            battery_offset = settings.strategy_1_battery_power_offset_w

            power_grid_value = settings.strategy_1_power_grid_value_w
            power_grid_dead_zone = settings.strategy_1_power_grid_dead_zone_w
            if settings.only_use_power_above_export_limit:
                power_grid_offset = settings.strategy_1_power_grid_offset_export_limit_w
            else:
                power_grid_offset = settings.strategy_1_power_grid_offset_w
            grid_upper = power_grid_offset + (power_grid_dead_zone / 2)
            grid_lower = power_grid_offset - (power_grid_dead_zone / 2)

            coil_power_w = settings.heating_coil_power * 1000  # kW → W

            # Určenie scenára
            battery_is_charging = (
                str(battery_charging_enabled).lower() == "on" and battery_soc < 100
            )
            export_on = (str(grid_export_status).lower() == "on")

            if battery_is_charging and not export_on:
                scenario = 1
            elif battery_is_charging and export_on:
                scenario = 2
            elif not battery_is_charging and not export_on:
                scenario = 3
            else:
                scenario = 4

            # Mŕtva zóna batérie: keď sa batéria nenabíja (Scenár 3, 4), offset sa ignoruje
            # (centrum mŕtvej zóny je 0W, nie nakonfigurovaný offset).
            # Spodná hranica môže byť záporná – pri nenabíjaní batéria nikdy nedosiahne
            # záporné hodnoty, takže ramp UP sa z dolnej hranice nespustí.
            effective_battery_offset = battery_offset if battery_is_charging else 0
            battery_upper = effective_battery_offset + (battery_dead_zone / 2)
            battery_lower = effective_battery_offset - (battery_dead_zone / 2)

            LOGGER.debug(
                "PowerAutomation STRATEGY 1 scenario=%d: export=%s, charging=%s, SOC=%.0f%%, "
                "grid=%dW [%.0f..%.0f], battery=%dW [%.0f..%.0f]",
                scenario, grid_export_status, battery_charging_enabled, battery_soc,
                power_grid_value, grid_lower, grid_upper,
                battery_power, battery_lower, battery_upper,
            )

            # Povolené smery podľa scenára
            battery_ramp_up_allowed = battery_is_charging  # Scenáre 1 & 2
            battery_ramp_down_allowed = True               # Všetky scenáre

            if scenario == 1:
                # Len batéria, grid ignorovaný
                grid_ramp_up_allowed = False
                grid_ramp_down_allowed = False
                probing_enabled = False  # Batéria aktívne nabíja – ramp UP riadi batéria, nie probing
            elif scenario == 2:
                # Batéria + grid (len export → UP, import ignorovaný)
                grid_ramp_up_allowed = True
                grid_ramp_down_allowed = False
                probing_enabled = False  # Export aj batéria dávajú dostatok signálu – probing zbytočný
            elif scenario == 3:
                # Batéria(DOWN) + grid(import → DOWN) + probing v kľudovom stave
                # Probing má zmysel: export je OFF, batéria nenabíja (SOC=100 alebo zakázané)
                # → jedinou cestou ako zistiť dostupný výkon FV je postupné krokovanie nahor
                grid_ramp_up_allowed = False
                grid_ramp_down_allowed = True
                probing_enabled = True
            else:  # scenario 4
                # Batéria(DOWN) + grid(oba smery)
                # Export je ON → grid sám určí smer, probing zbytočný
                grid_ramp_up_allowed = True
                grid_ramp_down_allowed = True
                probing_enabled = False

            # Výpočet príspevku batérie
            battery_delta = self._strategy_1_battery_delta(
                battery_power=battery_power,
                upper=battery_upper,
                lower=battery_lower,
                ramp_up_allowed=battery_ramp_up_allowed,
                ramp_down_allowed=battery_ramp_down_allowed,
                coil_power_w=coil_power_w,
                settings=settings,
            )

            # Výpočet príspevku gridu
            grid_delta = self._strategy_1_grid_delta(
                power_grid_value=power_grid_value,
                upper=grid_upper,
                lower=grid_lower,
                ramp_up_allowed=grid_ramp_up_allowed,
                ramp_down_allowed=grid_ramp_down_allowed,
                coil_power_w=coil_power_w,
                settings=settings,
            )

            # Priorita batérie: ak batéria žiada ramp DOWN a grid žiada ramp UP → ignorovať grid
            if (battery_delta is not None and battery_delta < 0
                    and grid_delta is not None and grid_delta > 0):
                LOGGER.debug(
                    "PowerAutomation STRATEGY 1 priority: battery DOWN (%.1f) vs grid UP (%.1f) → ignoring grid",
                    battery_delta, grid_delta,
                )
                grid_delta = None

            # Kombinácia príspevkov
            delta = 0.0
            if battery_delta is not None:
                delta += battery_delta
            if grid_delta is not None:
                delta += grid_delta

            # Clamp: výsledný krok nesmie presiahnuť najväčší jednotlivý príspevok
            max_contribution = max(
                abs(battery_delta) if battery_delta is not None else 0.0,
                abs(grid_delta) if grid_delta is not None else 0.0,
            )
            if max_contribution > 0 and abs(delta) > max_contribution:
                clamped = max_contribution if delta > 0 else -max_contribution
                LOGGER.debug(
                    "PowerAutomation STRATEGY 1 delta clamped: %.1f → %.1f",
                    delta, clamped,
                )
                delta = clamped

            # Probing (Scenár 3): oba zdroje v mŕtvej zóne → pomalý krok nahor
            if probing_enabled and battery_delta is None and grid_delta is None and delta == 0.0:
                probe_step = float(settings.strategy_1_ramp_up_slow_power_step)
                if probe_step > 0:
                    delta = probe_step
                    LOGGER.debug(
                        "PowerAutomation STRATEGY 1 probing: slow step UP %.1f%%",
                        probe_step,
                    )

            if delta != 0.0:
                new_output = max(0.0, min(100.0, self._current_output + delta))
                LOGGER.debug(
                    "PowerAutomation STRATEGY 1 result: %.1f%% → %.1f%% (delta=%.1f, battery=%s, grid=%s, scenario=%d)",
                    self._current_output, new_output, delta, battery_delta, grid_delta, scenario,
                )
                self._current_output = new_output

            result = max(0, min(100, int(round(self._current_output))))
            return result


        # ---------------------------------------------------------------
        # Strategy 2 – Grid + Solar (bez batérie)
        #
        # Scenáre podľa stavu exportu:
        # Scenár A: EXPORT=OFF → len grid (import → DOWN) + probing
        # Scenár B: EXPORT=ON  → grid (export → UP, import → DOWN) + probing
        #
        # Solar sensor slúži len ako rýchly DROP detektor (fast ramp down
        # pri prudkom poklese slnečného žiarenia), rovnako ako v Strategy 1.
        # ---------------------------------------------------------------
        if strategy == POWER_CONTROL_STRATEGY_2:

            if not settings.strategy_2_grid_export_status_entity_available:
                return 100
            if not settings.strategy_2_power_grid_entity_available:
                return 100

            grid_export_status = settings.strategy_2_grid_export_status_value
            export_on = (str(grid_export_status).lower() == "on")

            power_grid_value = settings.strategy_2_power_grid_value_w
            power_grid_dead_zone = settings.strategy_2_power_grid_dead_zone_w
            if settings.only_use_power_above_export_limit:
                power_grid_offset = settings.strategy_2_power_grid_offset_export_limit_w
            else:
                power_grid_offset = settings.strategy_2_power_grid_offset_w
            grid_upper = power_grid_offset + (power_grid_dead_zone / 2)
            grid_lower = power_grid_offset - (power_grid_dead_zone / 2)

            coil_power_w = settings.heating_coil_power * 1000

            if not export_on:
                scenario = "A"   # Export OFF – len import → DOWN + probing
                # Probing má zmysel: export je OFF, jedinou cestou ako zistiť
                # dostupný výkon FV je postupné krokovanie nahor
                grid_ramp_up_allowed = False
                grid_ramp_down_allowed = True
                probing_enabled = True
            else:
                scenario = "B"   # Export ON – oba smery, probing zbytočný
                grid_ramp_up_allowed = True
                grid_ramp_down_allowed = True
                probing_enabled = False

            LOGGER.debug(
                "PowerAutomation STRATEGY 2 scenario=%s: export=%s, "
                "grid=%dW [%.0f..%.0f]",
                scenario, grid_export_status,
                power_grid_value, grid_lower, grid_upper,
            )

            # Výpočet príspevku gridu (vlastná helper metóda pre Strategy 2)
            grid_delta = self._strategy_2_grid_delta(
                power_grid_value=power_grid_value,
                upper=grid_upper,
                lower=grid_lower,
                ramp_up_allowed=grid_ramp_up_allowed,
                ramp_down_allowed=grid_ramp_down_allowed,
                coil_power_w=coil_power_w,
                settings=settings,
            )

            delta = 0.0
            if grid_delta is not None:
                delta = grid_delta

            # Probing: grid v mŕtvej zóne → pomalý krok nahor (len v Scenári A)
            if probing_enabled and grid_delta is None and delta == 0.0:
                probe_step = float(settings.strategy_2_ramp_up_slow_power_step)
                if probe_step > 0:
                    delta = probe_step
                    LOGGER.debug(
                        "PowerAutomation STRATEGY 2 probing: slow step UP %.1f%%",
                        probe_step,
                    )

            if delta != 0.0:
                new_output = max(0.0, min(100.0, self._current_output + delta))
                LOGGER.debug(
                    "PowerAutomation STRATEGY 2 result: %.1f%% → %.1f%% (delta=%.1f, grid=%s, scenario=%s)",
                    self._current_output, new_output, delta, grid_delta, scenario,
                )
                self._current_output = new_output

            result = max(0, min(100, int(round(self._current_output))))
            return result


        # ---------------------------------------------------------------
        # Solar sensor
        # ---------------------------------------------------------------
        if strategy == POWER_CONTROL_STRATEGY_SOLAR_SENSOR:
            if not settings.solar_sensor_entity_available:
                return 100
            attenuation = settings.solar_sensor_attenuation
            solar_percent = settings.solar_radiation_value_percent
            target = (100 - attenuation) + (attenuation * solar_percent / 100)
            target = max(0.0, min(100.0, target))
            self._current_output = self._process_solar_ramp(
                target=target,
                current_output=self._current_output,
                ramp_up_step=settings.solar_sensor_ramp_up_power_step,
                ramp_up_cycle=settings.solar_sensor_ramp_up_power_cycle,
                ramp_down_step=settings.solar_sensor_ramp_down_power_step,
                ramp_down_cycle=settings.solar_sensor_ramp_down_power_cycle,
            )
            LOGGER.debug(
                "PowerAutomation solar: solar=%.1f%%, attenuation=%d, target=%.1f%%, output=%.1f%%",
                solar_percent, attenuation, target, self._current_output,
            )
            if abs(self._current_output - target) > 0.01:
                if target > self._current_output and settings.solar_sensor_ramp_up_power_step > 0:
                    self._set_ramp_delay(settings.solar_sensor_ramp_up_power_cycle)
                elif target < self._current_output and settings.solar_sensor_ramp_down_power_step > 0:
                    self._set_ramp_delay(settings.solar_sensor_ramp_down_power_cycle)

            result = max(0, min(100, int(round(self._current_output))))
            return result

        # ---------------------------------------------------------------
        # PV power
        # ---------------------------------------------------------------
        if strategy == POWER_CONTROL_STRATEGY_PV_POWER:
            if not settings.pv_power_entity_available:
                return 100
            attenuation = settings.pv_power_ratio
            pv_percent = settings.pv_power_max_power_percent
            target = pv_percent * attenuation / 100
            target = max(0.0, min(100.0, target))
            self._current_output = self._process_pv_power_ramp(
                target=target,
                current_output=self._current_output,
                ramp_up_step=settings.pv_power_ramp_up_power_step,
                ramp_up_cycle=settings.pv_power_ramp_up_power_cycle,
                ramp_down_step=settings.pv_power_ramp_down_power_step,
                ramp_down_cycle=settings.pv_power_ramp_down_power_cycle,
            )
            LOGGER.debug(
                "PowerAutomation pv: pv=%.1f%%, ratio=%d, target=%.1f%%, output=%.1f%%",
                pv_percent, attenuation, target, self._current_output,
            )
            if abs(self._current_output - target) > 0.01:
                if target > self._current_output and settings.pv_power_ramp_up_power_step > 0:
                    self._set_ramp_delay(settings.pv_power_ramp_up_power_cycle)
                elif target < self._current_output and settings.pv_power_ramp_down_power_step > 0:
                    self._set_ramp_delay(settings.pv_power_ramp_down_power_cycle)

            result = max(0, min(100, int(round(self._current_output))))
            return result

        # ---------------------------------------------------------------
        # Power grid – balancovanie prietoku na elektromeri
        # ---------------------------------------------------------------
        if strategy == POWER_CONTROL_STRATEGY_POWER_GRID:
            if not settings.power_grid_entity_available:
                return 100
            grid_w = settings.power_grid_value_w
            dead_zone = settings.power_grid_dead_zone_w
            if settings.only_use_power_above_export_limit:
                offset = settings.power_grid_offset_export_limit_w
            else:
                offset = settings.power_grid_offset_w
            upper_threshold = offset + (dead_zone / 2)
            lower_threshold = offset - (dead_zone / 2)
            self._current_output = self._process_power_grid_ramp(
                grid_value_w=grid_w,
                upper_threshold=upper_threshold,
                lower_threshold=lower_threshold,
                current_output=self._current_output,
                ramp_up_step=settings.power_grid_ramp_up_power_step,
                ramp_up_cycle=settings.power_grid_ramp_up_power_cycle,
                ramp_down_step=settings.power_grid_ramp_down_power_step,
                ramp_down_cycle=settings.power_grid_ramp_down_power_cycle,
            )
            LOGGER.debug(
                "PowerAutomation grid: grid_w=%.1f, zone=[%.0f..%.0f], output=%.1f%%",
                grid_w, lower_threshold, upper_threshold, self._current_output,
            )
            if grid_w > upper_threshold and settings.power_grid_ramp_up_power_step > 0 and self._current_output < 100:
                self._set_ramp_delay(settings.power_grid_ramp_up_power_cycle)
            elif grid_w < lower_threshold and settings.power_grid_ramp_down_power_step > 0 and self._current_output > 0:
                self._set_ramp_delay(settings.power_grid_ramp_down_power_cycle)

            result = max(0, min(100, int(round(self._current_output))))
            return result

        # ---------------------------------------------------------------
        # Battery power
        # ---------------------------------------------------------------
        # ---------------------------------------------------------------
        # Battery power – obrátená logika oproti power_grid
        # Nabíjanie (kladná hodnota) → znížiť výkon špirály (batéria potrebuje energiu)
        # Vybíjanie (záporná hodnota) → zvýšiť výkon špirály (batéria dodáva energiu)
        # ---------------------------------------------------------------
        if strategy == POWER_CONTROL_STRATEGY_BATTERY:
            if not settings.battery_power_entity_available:
                return 100
            battery_w = settings.battery_power_value_w
            dead_zone = settings.battery_power_dead_zone_w
            offset = settings.battery_power_offset_w
            upper_threshold = offset + (dead_zone / 2)
            lower_threshold = offset - (dead_zone / 2)
            self._current_output = self._process_battery_power_ramp(
                battery_value_w=battery_w,
                upper_threshold=upper_threshold,
                lower_threshold=lower_threshold,
                current_output=self._current_output,
                ramp_up_step=settings.battery_power_ramp_up_power_step,
                ramp_up_cycle=settings.battery_power_ramp_up_power_cycle,
                ramp_down_step=settings.battery_power_ramp_down_power_step,
                ramp_down_cycle=settings.battery_power_ramp_down_power_cycle,
            )
            LOGGER.debug(
                "PowerAutomation battery: battery_w=%.1f, zone=[%.0f..%.0f], output=%.1f%%",
                battery_w, lower_threshold, upper_threshold, self._current_output,
            )
            # Obrátená logika: nabíjanie → ramp down, vybíjanie → ramp up
            if battery_w > upper_threshold and settings.battery_power_ramp_down_power_step > 0 and self._current_output > 0:
                self._set_ramp_delay(settings.battery_power_ramp_down_power_cycle)
            elif battery_w < lower_threshold and settings.battery_power_ramp_up_power_step > 0 and self._current_output < 100:
                self._set_ramp_delay(settings.battery_power_ramp_up_power_cycle)

            result = max(0, min(100, int(round(self._current_output))))
            return result

        # ---------------------------------------------------------------
        # Neznáma stratégia → žiadne obmedzenie
        # ---------------------------------------------------------------
        LOGGER.warning("PowerAutomation: unknown strategy '%s', returning 100%%", strategy)
        return 100

    def _set_ramp_delay(self, cycle_seconds: float) -> None:
        """Nastaví ramp_active a aktualizuje next_ramp_delay (minimálny zo všetkých zdrojov)."""
        if cycle_seconds <= 0:
            cycle_seconds = 1
        self._ramp_active = True
        if self._next_ramp_delay <= 0:
            self._next_ramp_delay = cycle_seconds
        else:
            self._next_ramp_delay = min(self._next_ramp_delay, cycle_seconds)

    # ===================================================================
    # Privátne metódy – rampa pre solárny senzor
    # ===================================================================

    def _process_solar_ramp(
        self,
        target: float,
        current_output: float,
        ramp_up_step: int,
        ramp_up_cycle: int,
        ramp_down_step: int,
        ramp_down_cycle: int,
    ) -> float:
        """Spracovanie rampovania výkonu podľa solárneho senzora.

        Ak je target > current → rampa hore (ramp up).
        Ak je target < current → rampa dole (ramp down).
        Ak je step = 0, príslušný smer je vypnutý.

        Aplikuje maximálne jeden krok na volanie. Ďalší krok sa vykoná
        pri ďalšom zavolaní controllera (naplánovanom cez self-scheduling).

        Args:
            target: cieľová hodnota výkonu (solar_radiation_value_percent)
            current_output: aktuálna hodnota výstupu automatizácie
            ramp_up_step: veľkosť kroku pri zvyšovaní [%]
            ramp_up_cycle: čas medzi krokmi pri zvyšovaní [s]
            ramp_down_step: veľkosť kroku pri znižovaní [%]
            ramp_down_cycle: čas medzi krokmi pri znižovaní [s]

        Returns:
            float: nová hodnota výstupu po aplikácii rampy
        """
        now = time.monotonic()

        if target > current_output:
            # Zvyšovanie výkonu
            if ramp_up_step == 0:
                LOGGER.debug("PowerAutomation solar ramp_up disabled (step=0)")
                return current_output

            if ramp_up_cycle <= 0:
                ramp_up_cycle = 1

            elapsed = now - self._solar_last_ramp_time
            if elapsed >= ramp_up_cycle:
                new_output = min(target, current_output + ramp_up_step)
                self._solar_last_ramp_time = now
                LOGGER.debug(
                    "PowerAutomation solar ramp UP: %.1f → %.1f (step=%d, elapsed=%.1fs)",
                    current_output, new_output, ramp_up_step, elapsed,
                )
                return new_output

        elif target < current_output:
            # Znižovanie výkonu
            if ramp_down_step == 0:
                LOGGER.debug("PowerAutomation solar ramp_down disabled (step=0)")
                return current_output

            if ramp_down_cycle <= 0:
                ramp_down_cycle = 1

            elapsed = now - self._solar_last_ramp_time
            if elapsed >= ramp_down_cycle:
                new_output = max(target, current_output - ramp_down_step)
                self._solar_last_ramp_time = now
                LOGGER.debug(
                    "PowerAutomation solar ramp DOWN: %.1f → %.1f (step=%d, elapsed=%.1fs)",
                    current_output, new_output, ramp_down_step, elapsed,
                )
                return new_output

        # Target == current alebo ešte neuplynul čas cyklu
        return current_output

    # ===================================================================
    # Privátne metódy – rampa pre PV výkon
    # ===================================================================

    def _process_pv_power_ramp(
        self,
        target: float,
        current_output: float,
        ramp_up_step: int,
        ramp_up_cycle: int,
        ramp_down_step: int,
        ramp_down_cycle: int,
    ) -> float:
        """Spracovanie rampovania výkonu podľa PV výkonu.

        Analogické k _process_solar_ramp, ale používa vlastný časovač.

        Args:
            target: cieľová hodnota výkonu (z pv_power_max_power_percent * pv_power_ratio)
            current_output: aktuálna hodnota výstupu automatizácie
            ramp_up_step: veľkosť kroku pri zvyšovaní [%]
            ramp_up_cycle: čas medzi krokmi pri zvyšovaní [s]
            ramp_down_step: veľkosť kroku pri znižovaní [%]
            ramp_down_cycle: čas medzi krokmi pri znižovaní [s]

        Returns:
            float: nová hodnota výstupu po aplikácii rampy
        """
        now = time.monotonic()

        if target > current_output:
            if ramp_up_step == 0:
                LOGGER.debug("PowerAutomation pv ramp_up disabled (step=0)")
                return current_output

            if ramp_up_cycle <= 0:
                ramp_up_cycle = 1

            elapsed = now - self._pv_last_ramp_time
            if elapsed >= ramp_up_cycle:
                new_output = min(target, current_output + ramp_up_step)
                self._pv_last_ramp_time = now
                LOGGER.debug(
                    "PowerAutomation pv ramp UP: %.1f → %.1f (step=%d, elapsed=%.1fs)",
                    current_output, new_output, ramp_up_step, elapsed,
                )
                return new_output

        elif target < current_output:
            if ramp_down_step == 0:
                LOGGER.debug("PowerAutomation pv ramp_down disabled (step=0)")
                return current_output

            if ramp_down_cycle <= 0:
                ramp_down_cycle = 1

            elapsed = now - self._pv_last_ramp_time
            if elapsed >= ramp_down_cycle:
                new_output = max(target, current_output - ramp_down_step)
                self._pv_last_ramp_time = now
                LOGGER.debug(
                    "PowerAutomation pv ramp DOWN: %.1f → %.1f (step=%d, elapsed=%.1fs)",
                    current_output, new_output, ramp_down_step, elapsed,
                )
                return new_output

        # Target == current alebo ešte neuplynul čas cyklu
        return current_output

    # ===================================================================
    # Privátne metódy – rampa pre riadenie podľa elektromera
    # ===================================================================

    def _process_power_grid_ramp(
        self,
        grid_value_w: float,
        upper_threshold: float,
        lower_threshold: float,
        current_output: float,
        ramp_up_step: int,
        ramp_up_cycle: int,
        ramp_down_step: int,
        ramp_down_cycle: int,
    ) -> float:
        """Spracovanie rampovania výkonu podľa prietoku na elektromeri.

        Cieľom je vybalancovať prietok energie cez elektromer.
        Ak grid_value_w > upper_threshold → zvýšiť výkon špirály (prebytok).
        Ak grid_value_w < lower_threshold → znížiť výkon špirály (odber).
        Medzi lower_threshold a upper_threshold → výkon sa nemení (mŕtva zóna).

        Prahy sú vypočítané z dead_zone a offset:
            upper_threshold = offset + dead_zone
            lower_threshold = offset - dead_zone

        Args:
            grid_value_w: aktuálna hodnota z elektromera [W]
            upper_threshold: horný prah mŕtvej zóny [W]
            lower_threshold: dolný prah mŕtvej zóny [W]
            current_output: aktuálna hodnota výstupu automatizácie [%]
            ramp_up_step: veľkosť kroku pri zvyšovaní [%]
            ramp_up_cycle: čas medzi krokmi pri zvyšovaní [s]
            ramp_down_step: veľkosť kroku pri znižovaní [%]
            ramp_down_cycle: čas medzi krokmi pri znižovaní [s]

        Returns:
            float: nová hodnota výstupu po aplikácii rampy
        """
        now = time.monotonic()

        if grid_value_w > upper_threshold:
            # Prebytok – zvyšovať výkon špirály
            if ramp_up_step == 0:
                LOGGER.debug("PowerAutomation grid ramp_up disabled (step=0)")
                return current_output

            if ramp_up_cycle <= 0:
                ramp_up_cycle = 1

            elapsed = now - self._power_grid_last_ramp_time
            if elapsed >= ramp_up_cycle:
                new_output = min(100.0, current_output + ramp_up_step)
                self._power_grid_last_ramp_time = now
                LOGGER.debug(
                    "PowerAutomation grid ramp UP: %.1f → %.1f (step=%d, grid=%.0fW, threshold=%.0f, elapsed=%.1fs)",
                    current_output, new_output, ramp_up_step, grid_value_w, upper_threshold, elapsed,
                )
                return new_output

        elif grid_value_w < lower_threshold:
            # Odber – znižovať výkon špirály
            if ramp_down_step == 0:
                LOGGER.debug("PowerAutomation grid ramp_down disabled (step=0)")
                return current_output

            if ramp_down_cycle <= 0:
                ramp_down_cycle = 1

            elapsed = now - self._power_grid_last_ramp_time
            if elapsed >= ramp_down_cycle:
                new_output = max(0.0, current_output - ramp_down_step)
                self._power_grid_last_ramp_time = now
                LOGGER.debug(
                    "PowerAutomation grid ramp DOWN: %.1f → %.1f (step=%d, grid=%.0fW, threshold=%.0f, elapsed=%.1fs)",
                    current_output, new_output, ramp_down_step, grid_value_w, lower_threshold, elapsed,
                )
                return new_output

        # V mŕtvej zóne alebo ešte neuplynul čas cyklu
        return current_output

    # ===================================================================
    # Privátne metódy – rampa pre riadenie podľa batérie
    # ===================================================================

    def _process_battery_power_ramp(
        self,
        battery_value_w: float,
        upper_threshold: float,
        lower_threshold: float,
        current_output: float,
        ramp_up_step: int,
        ramp_up_cycle: int,
        ramp_down_step: int,
        ramp_down_cycle: int,
    ) -> float:
        """Spracovanie rampovania výkonu podľa výkonu batérie.

        Obrátená logika oproti power_grid:
        Ak battery_value_w > upper_threshold (nabíjanie) → znížiť výkon špirály.
        Ak battery_value_w < lower_threshold (vybíjanie) → zvýšiť výkon špirály.
        Medzi lower_threshold a upper_threshold → výkon sa nemení (mŕtva zóna).

        Args:
            battery_value_w: aktuálna hodnota z batérie [W]
            upper_threshold: horný prah mŕtvej zóny [W]
            lower_threshold: dolný prah mŕtvej zóny [W]
            current_output: aktuálna hodnota výstupu automatizácie [%]
            ramp_up_step: veľkosť kroku pri zvyšovaní výkonu špirály [%]
            ramp_up_cycle: čas medzi krokmi pri zvyšovaní [s]
            ramp_down_step: veľkosť kroku pri znižovaní výkonu špirály [%]
            ramp_down_cycle: čas medzi krokmi pri znižovaní [s]

        Returns:
            float: nová hodnota výstupu po aplikácii rampy
        """
        now = time.monotonic()

        if battery_value_w > upper_threshold:
            # Nabíjanie – znižovať výkon špirály (batéria potrebuje energiu)
            if ramp_down_step == 0:
                LOGGER.debug("PowerAutomation battery ramp_down disabled (step=0)")
                return current_output

            if ramp_down_cycle <= 0:
                ramp_down_cycle = 1

            elapsed = now - self._battery_last_ramp_time
            if elapsed >= ramp_down_cycle:
                new_output = max(0.0, current_output - ramp_down_step)
                self._battery_last_ramp_time = now
                LOGGER.debug(
                    "PowerAutomation battery ramp DOWN: %.1f → %.1f (step=%d, battery=%.0fW, threshold=%.0f, elapsed=%.1fs)",
                    current_output, new_output, ramp_down_step, battery_value_w, upper_threshold, elapsed,
                )
                return new_output

        elif battery_value_w < lower_threshold:
            # Vybíjanie – zvyšovať výkon špirály (batéria dodáva energiu)
            if ramp_up_step == 0:
                LOGGER.debug("PowerAutomation battery ramp_up disabled (step=0)")
                return current_output

            if ramp_up_cycle <= 0:
                ramp_up_cycle = 1

            elapsed = now - self._battery_last_ramp_time
            if elapsed >= ramp_up_cycle:
                new_output = min(100.0, current_output + ramp_up_step)
                self._battery_last_ramp_time = now
                LOGGER.debug(
                    "PowerAutomation battery ramp UP: %.1f → %.1f (step=%d, battery=%.0fW, threshold=%.0f, elapsed=%.1fs)",
                    current_output, new_output, ramp_up_step, battery_value_w, lower_threshold, elapsed,
                )
                return new_output

        # V mŕtvej zóne alebo ešte neuplynul čas cyklu
        return current_output

    def _strategy_1_battery_delta(
        self,
        battery_power: float,
        upper: float,
        lower: float,
        ramp_up_allowed: bool,
        ramp_down_allowed: bool,
        coil_power_w: float,
        settings,
    ) -> float | None:
        """Vypočíta príspevok batérie pre Strategy 1.

        battery_power > 0: vybíjanie (odber z batérie) → ramp DOWN
        battery_power < 0: dobíjanie (energia ide do batérie) → ramp UP
        upper/lower: okraje mŕtvej zóny (offset ± dead_zone/2)

        Cap algoritmus pri ramp UP: rýchly krok nesmie presiahnuť
        dostupný výkon (vzdialenosť od okraja mŕtvej zóny vo wattoch).
        Ak by presiahol, použije sa pomalý krok.
        """
        # Vybíjanie batérie (battery_power > upper) → ramp DOWN
        if ramp_down_allowed and battery_power > upper:
            if battery_power >= settings.strategy_1_battery_ramp_down_fast_threshold:
                step = settings.strategy_1_ramp_down_fast_power_step
                LOGGER.debug(
                    "STRATEGY 1 battery FAST DOWN: step=%d, battery=%.0fW, threshold=%.0f",
                    step, battery_power, settings.strategy_1_battery_ramp_down_fast_threshold,
                )
            else:
                step = settings.strategy_1_ramp_down_slow_power_step
                LOGGER.debug(
                    "STRATEGY 1 battery slow DOWN: step=%d, battery=%.0fW",
                    step, battery_power,
                )
            return -float(step) if step > 0 else None

        # Dobíjanie batérie (battery_power < lower) → ramp UP (s cap algoritmom)
        if ramp_up_allowed and battery_power < lower:
            available_w = abs(battery_power - lower)
            charging_power = abs(battery_power)

            if charging_power >= settings.strategy_1_battery_ramp_up_fast_threshold:
                # Chceme rýchly krok – skontrolujeme cap
                fast_step_w = (settings.strategy_1_ramp_up_fast_power_step / 100.0) * coil_power_w
                if fast_step_w <= available_w:
                    step = settings.strategy_1_ramp_up_fast_power_step
                    LOGGER.debug(
                        "STRATEGY 1 battery FAST UP: step=%d, battery=%.0fW, available=%.0fW",
                        step, battery_power, available_w,
                    )
                else:
                    step = settings.strategy_1_ramp_up_slow_power_step
                    LOGGER.debug(
                        "STRATEGY 1 battery FAST→SLOW UP (capped): step=%d, battery=%.0fW, "
                        "available=%.0fW, fast_would_be=%.0fW",
                        step, battery_power, available_w, fast_step_w,
                    )
            else:
                step = settings.strategy_1_ramp_up_slow_power_step
                LOGGER.debug(
                    "STRATEGY 1 battery slow UP: step=%d, battery=%.0fW",
                    step, battery_power,
                )
            return float(step) if step > 0 else None

        # V mŕtvej zóne
        return None

    def _strategy_1_grid_delta(
        self,
        power_grid_value: float,
        upper: float,
        lower: float,
        ramp_up_allowed: bool,
        ramp_down_allowed: bool,
        coil_power_w: float,
        settings,
    ) -> float | None:
        """Vypočíta príspevok gridu pre Strategy 1.

        power_grid_value > 0: export do siete → ramp UP
        power_grid_value < 0: import zo siete → ramp DOWN
        upper/lower: okraje mŕtvej zóny (offset ± dead_zone/2)

        Cap algoritmus pri ramp UP: rýchly krok nesmie presiahnuť
        dostupný výkon exportu (vzdialenosť od okraja mŕtvej zóny).
        Ak by presiahol, použije sa pomalý krok.
        """
        # Import zo siete (power_grid_value < lower) → ramp DOWN
        if ramp_down_allowed and power_grid_value < lower:
            import_power = abs(power_grid_value)
            if import_power >= settings.strategy_1_power_grid_ramp_down_fast_threshold:
                step = settings.strategy_1_ramp_down_fast_power_step
                LOGGER.debug(
                    "STRATEGY 1 grid FAST DOWN: step=%d, grid=%.0fW, threshold=%.0f",
                    step, power_grid_value, settings.strategy_1_power_grid_ramp_down_fast_threshold,
                )
            else:
                step = settings.strategy_1_ramp_down_slow_power_step
                LOGGER.debug(
                    "STRATEGY 1 grid slow DOWN: step=%d, grid=%.0fW",
                    step, power_grid_value,
                )
            return -float(step) if step > 0 else None

        # Export do siete (power_grid_value > upper) → ramp UP (s cap algoritmom)
        if ramp_up_allowed and power_grid_value > upper:
            available_w = power_grid_value - upper

            if power_grid_value >= settings.strategy_1_power_grid_ramp_up_fast_threshold:
                # Chceme rýchly krok – skontrolujeme cap
                fast_step_w = (settings.strategy_1_ramp_up_fast_power_step / 100.0) * coil_power_w
                if fast_step_w <= available_w:
                    step = settings.strategy_1_ramp_up_fast_power_step
                    LOGGER.debug(
                        "STRATEGY 1 grid FAST UP: step=%d, grid=%.0fW, available=%.0fW",
                        step, power_grid_value, available_w,
                    )
                else:
                    step = settings.strategy_1_ramp_up_slow_power_step
                    LOGGER.debug(
                        "STRATEGY 1 grid FAST→SLOW UP (capped): step=%d, grid=%.0fW, "
                        "available=%.0fW, fast_would_be=%.0fW",
                        step, power_grid_value, available_w, fast_step_w,
                    )
            else:
                step = settings.strategy_1_ramp_up_slow_power_step
                LOGGER.debug(
                    "STRATEGY 1 grid slow UP: step=%d, grid=%.0fW",
                    step, power_grid_value,
                )
            return float(step) if step > 0 else None

        # V mŕtvej zóne
        return None

    def _strategy_2_grid_delta(
        self,
        power_grid_value: float,
        upper: float,
        lower: float,
        ramp_up_allowed: bool,
        ramp_down_allowed: bool,
        coil_power_w: float,
        settings,
    ) -> float | None:
        """Vypočíta príspevok gridu pre Strategy 2 (Grid + Solar, bez batérie).

        Identická logika ako _strategy_1_grid_delta, číta však strategy_2_* settings.
        """
        # Import zo siete (power_grid_value < lower) → ramp DOWN
        if ramp_down_allowed and power_grid_value < lower:
            import_power = abs(power_grid_value)
            if import_power >= settings.strategy_2_power_grid_ramp_down_fast_threshold:
                step = settings.strategy_2_ramp_down_fast_power_step
                LOGGER.debug(
                    "STRATEGY 2 grid FAST DOWN: step=%d, grid=%.0fW, threshold=%.0f",
                    step, power_grid_value, settings.strategy_2_power_grid_ramp_down_fast_threshold,
                )
            else:
                step = settings.strategy_2_ramp_down_slow_power_step
                LOGGER.debug(
                    "STRATEGY 2 grid slow DOWN: step=%d, grid=%.0fW",
                    step, power_grid_value,
                )
            return -float(step) if step > 0 else None

        # Export do siete (power_grid_value > upper) → ramp UP (s cap algoritmom)
        if ramp_up_allowed and power_grid_value > upper:
            available_w = power_grid_value - upper

            if power_grid_value >= settings.strategy_2_power_grid_ramp_up_fast_threshold:
                fast_step_w = (settings.strategy_2_ramp_up_fast_power_step / 100.0) * coil_power_w
                if fast_step_w <= available_w:
                    step = settings.strategy_2_ramp_up_fast_power_step
                    LOGGER.debug(
                        "STRATEGY 2 grid FAST UP: step=%d, grid=%.0fW, available=%.0fW",
                        step, power_grid_value, available_w,
                    )
                else:
                    step = settings.strategy_2_ramp_up_slow_power_step
                    LOGGER.debug(
                        "STRATEGY 2 grid FAST→SLOW UP (capped): step=%d, grid=%.0fW, "
                        "available=%.0fW, fast_would_be=%.0fW",
                        step, power_grid_value, available_w, fast_step_w,
                    )
            else:
                step = settings.strategy_2_ramp_up_slow_power_step
                LOGGER.debug(
                    "STRATEGY 2 grid slow UP: step=%d, grid=%.0fW",
                    step, power_grid_value,
                )
            return float(step) if step > 0 else None

        # V mŕtvej zóne
        return None
