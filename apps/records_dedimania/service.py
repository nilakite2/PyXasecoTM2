"""Configuration schema for Dedimania records."""

from pyxaseco.app_config import AppSetting, AppSettingsSchema, as_int


DEDI_TIMEOUT  = 1800
DEDI_REFRESH  = 240
DEDI_SETTINGS_SCHEMA = AppSettingsSchema(
    app_id='records_dedimania',
    description='Typed Records Dedimania app defaults.',
    settings=(
        AppSetting('dedi_timeout', DEDI_TIMEOUT, as_int, 'Dedimania timeout threshold in seconds.', 'network'),
        AppSetting('dedi_refresh', DEDI_REFRESH, as_int, 'Dedimania refresh interval in seconds.', 'network'),
    ),
)



