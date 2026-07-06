# Translations

The WDG client is internationalized via the standard Python `gettext` module.

## Layout

```
locales/
├── wdg.pot                      # message template (generated)
└── fr/
    └── LC_MESSAGES/
        ├── wdg.po               # French source translations (edit this)
        └── wdg.mo               # compiled catalog (generated, loaded at runtime)
```

## Runtime language selection

In order of precedence:

1. `WDG_LANG` environment variable (e.g. `WDG_LANG=fr`)
2. Standard gettext env vars: `LC_ALL`, `LC_MESSAGES`, `LANG`
3. Fallback: untranslated source strings (English)

Examples:

```bash
wg-client --help              # English (default)
WDG_LANG=fr wg-client --help  # French
LANG=fr_FR.UTF-8 wg-client --help
```

## Adding or updating strings

1. Wrap new user-facing strings in `_(...)` in the Python source.
2. Regenerate the `.pot` template from the client package root:

   ```bash
   xgettext --language=Python --from-code=UTF-8 --keyword=_ \
       --output=locales/wdg.pot \
       --package-name=wdg --package-version=0.1 \
       main.py ops.py gui.py auth.py tunnel.py plan.py pqtls.py
   ```

3. Merge the new strings into the French catalog:

   ```bash
   msgmerge --update locales/fr/LC_MESSAGES/wdg.po locales/wdg.pot
   ```

4. Translate the new entries in `locales/fr/LC_MESSAGES/wdg.po`.

5. Compile:

   ```bash
   msgfmt --check --statistics \
       -o locales/fr/LC_MESSAGES/wdg.mo \
          locales/fr/LC_MESSAGES/wdg.po
   ```

### Using pybabel (if the gettext CLI isn't installed)

The same three steps with [Babel](https://babel.pocoo.org/) (a `babel.cfg` with
`[python: **.py]` is included):

```bash
pybabel extract -F babel.cfg -k _ -o locales/wdg.pot .   # extract
pybabel update  -i locales/wdg.pot -d locales -D wdg -l fr   # merge into fr
pybabel compile -d locales -D wdg -l fr --statistics         # compile .mo
```

## Adding a new language

```bash
msginit --input=locales/wdg.pot --locale=<xx> \
        --output=locales/<xx>/LC_MESSAGES/wdg.po
# ... translate ...
msgfmt -o locales/<xx>/LC_MESSAGES/wdg.mo \
          locales/<xx>/LC_MESSAGES/wdg.po
```

Replace `<xx>` with the target language code (e.g. `de`, `es`, `pt_BR`).
