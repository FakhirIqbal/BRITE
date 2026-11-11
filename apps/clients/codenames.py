"""Pool of nature words used to generate unique, searchable Client Code Names."""
import random

CODE_NAME_POOL = [
    "Juniper", "Aspen", "Fern", "Harbor", "Sparrow", "Sage", "Willow", "Coral", "Orchid", "Linden", "Rowan", "Birch",
    "Maple", "Cedar", "Oak", "Pine", "Ivy", "Hazel", "Aster", "Clover", "Dahlia", "Elm", "Heron", "Iris", "Jasper",
    "Kestrel", "Laurel", "Magnolia", "Nettle", "Olive", "Poppy", "Quince", "Reed", "Sorrel", "Thistle", "Umber", "Violet",
    "Wren", "Yarrow", "Zinnia", "Alder", "Basil", "Cypress", "Dune", "Ember", "Finch", "Garnet", "Holly", "Indigo",
    "Juneberry", "Kelp", "Lotus", "Meadow", "Nutmeg", "Osprey", "Pebble", "Quill", "Ripple", "Saffron", "Tamarack",
    "Upland", "Verbena", "Wisteria", "Yucca", "Zephyr", "Acacia", "Bramble", "Canyon", "Delta", "Everglade", "Fjord",
    "Glacier", "Harvest", "Inlet", "Jade", "Knoll", "Lagoon", "Marigold", "Nectar", "Opal", "Prairie", "Quartz", "Ridge",
    "Summit", "Tundra", "Vale", "Wildrose", "Amber", "Breeze", "Cobalt", "Dawn", "Estuary", "Flint", "Grove", "Horizon",
    "Islet", "Jonquil", "Lark", "Mesa", "Nimbus", "Orca", "Plover", "Rain", "Sequoia", "Tern", "Willet", "Zelkova",
]


def generate_code_name(existing: set[str]) -> str:
    existing_lower = {name.lower() for name in existing}
    pool = CODE_NAME_POOL[:]
    random.shuffle(pool)
    for name in pool:
        if name.lower() not in existing_lower:
            return name
    # Pool exhausted: append the smallest free number so the name stays unique and readable.
    base = random.choice(CODE_NAME_POOL)
    n = 2
    while f"{base} {n}".lower() in existing_lower:
        n += 1
    return f"{base} {n}"
