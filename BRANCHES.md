# Branch strategy

This fork tracks kernel compatibility per branch, since T2Touch's native
transport and the `applesmc` SEP boot-state publisher are kernel-ABI-coupled
in ways that don't survive every kernel bump unchanged.

- **`kernel-7.2.x`** (default branch) — tested working. This is where the
  2026-11-14/15 session validated everything: the 4 upstream bug fixes
  (observed-identity recovery's handle lookup, the post-reboot journal
  filter and `baseline_version` restriction, the multi-enrollment ambiguity
  fix), plus the login-greeter trust path in `t2_fprint_claim.py`. Known
  good on `linux-t2` 7.2.11 (MacBookPro16,1).

- **`kernel-7.3.x`** — work in progress, not yet working. `linux-t2` 7.3.x
  ships an in-tree `macsmc` driver stack (`macsmc_core`/`macsmc_acpi`/
  `macsmc_hwmon`/`macsmc_power`/`macsmc_wdt`/`rtc_macsmc`) that claims the
  `APP0001` ACPI SMC device before T2Touch's own patched `applesmc`
  (`applesmc-t2touch`) ever gets a chance — so no boot-state publisher,
  so `t2_sep_transport` never loads cleanly. Also hit the ACPI driver model
  change on this kernel (`struct acpi_driver`/`acpi_bus_register_driver`
  removed; a `platform_driver` port compiles fine but still can't bind
  because `macsmc` already owns the hardware). Real fix needs actual
  integration with (or displacement of) `macsmc`, not just an API port.
  Branched from `kernel-7.2.x` at the same commit; no code differs yet,
  this just marks where that investigation continues.

Future major kernel bumps that break compatibility again get their own
`kernel-X.Y.x` branch the same way, branched from whichever branch was
`main`/default at the time.
