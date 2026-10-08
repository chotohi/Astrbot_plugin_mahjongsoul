def try_parse_name(raw):
    return raw[3:] if raw.lower().startswith('id:') else None
