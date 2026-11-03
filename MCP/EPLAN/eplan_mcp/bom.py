"""Provisional planning quantities, deliberately separate from vendor parts data."""


def provisional_rows(model: dict) -> list[dict]:
    positions = {}
    for terminal in model["terminals"]:
        positions[terminal["strip"]] = positions.get(terminal["strip"], 0) + 1
    rows = []
    for device in model["devices"]:
        tag = device["tag"]
        if tag in {"AC_BUS", "DC_BUS", "PE_BUS"}:
            continue
        count = positions.get(tag, "")
        reference = model.get('reference_selection', {}).get(tag, {})
        selected = model.get('client_design_selection', {}).get('part_by_tag', {}).get(tag,{})
        rows.append({"tag": tag,
                     "name": device["name"] + (f"（{count}端子位）" if count else ""),
                     "quantity": "1", "unit": "逻辑组", "purchase_quantity": "TBD",
                     "terminal_positions": count,
                     "manufacturer": "Siemens" if tag == "PLC1" else "TBD", "part_number": "TBD",
                     "reference_manufacturer": selected.get('manufacturer',reference.get('manufacturer', 'TBD')),
                     "reference_part_number": selected.get('part_number',reference.get('reference_interface_article', reference.get('article_number', device.get('part_number', 'TBD')))) if model.get('reference_selection') else 'TBD',
                     "rating_or_size": device.get("voltage", "TBD"), "status": "provisional_unverified"})
    requirements = [
        ("PEBAR_REQ", "PE汇流排及安装连接件"), ("RAIL_REQ", "DIN导轨、端挡及固定件"),
        ("DUCT_REQ", "线槽、盖板及转角附件"), ("PESTRAP_REQ", "柜门PE跨接与接地五金"),
        ("WIRING_REQ", "导线、标识、端头与压接件"), ("GLAND_REQ", "电缆进出线与屏蔽附件"),
        ("RELAY_ACC_REQ", "继电器底座与线圈抑制附件"),
    ]
    for tag, name in requirements:
        rows.append({"tag": tag, "name": name, "quantity": "TBD", "unit": "待核算",
                     "purchase_quantity": "TBD", "terminal_positions": "", "manufacturer": "TBD",
                     "part_number": "TBD", "rating_or_size": "TBD", "status": "unquantified_requirement"})
        rows[-1]['reference_manufacturer']='TBD';rows[-1]['reference_part_number']='TBD'
    return rows
