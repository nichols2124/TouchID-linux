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

- **`kernel-7.3.x`** — tested working (2026-11-18). `linux-t2` 7.3.x removed
  the old ACPI driver model (`struct acpi_driver`/`acpi_bus_register_driver`)
  that `applesmc-t2touch` used; ported it to `platform_driver` (match via
  `.driver.acpi_match_table`, `ACPI_COMPANION()` to recover the `acpi_device`
  in probe). This was initially assumed blocked on top of that: 7.3.x also
  ships an in-tree `macsmc` driver stack (`macsmc_core`/`macsmc_acpi`/
  `macsmc_hwmon`/`macsmc_power`/`macsmc_wdt`/`rtc_macsmc`) that claims the
  `APP0001` ACPI SMC device before `applesmc-t2touch` ever gets a chance, so
  the ported module never binds to anything.

  That turned out not to matter. `t2_sep_transport`'s dependency on
  `applesmc` is purely a module-load-order + module-parameter handshake
  (`softdep t2_sep_transport pre: applesmc`, boot-state read from
  `/sys/module/applesmc/parameters/t2_sep_boot_state`) — a kernel module
  parameter is set as soon as the module *loads*, regardless of whether it
  ever binds to a device. So `applesmc-t2touch` loading (even unbound, with
  `macsmc` owning the actual hardware) is sufficient; no integration with or
  displacement of `macsmc` is needed. Confirmed end-to-end on real hardware:
  every `t2-touchid-doctor` check passes, `fprintd` runs, and Touch ID works
  through a real suspend/resume cycle too. `macsmc` keeps the sensor/power/
  RTC/watchdog functionality `applesmc-t2touch` never provided anyway.

  Only code difference from `kernel-7.2.x`: the `platform_driver` port in
  `packaging/applesmc-t2touch/applesmc.c`. Everything else tracks the
  default branch.

## Which branch to use

Check `uname -r` before cloning or switching: use `kernel-7.2.x` on `linux-t2`
7.2 or lower, `kernel-7.3.x` on 7.3 or higher. Nothing currently auto-detects
the running kernel and picks the right branch, so getting this wrong means an
`applesmc-t2touch` build that doesn't match your kernel's driver model. This
is a stopgap until the two branches are reconciled into one.

Future major kernel bumps that break compatibility again get their own
`kernel-X.Y.x` branch the same way, branched from whichever branch was
`main`/default at the time.
