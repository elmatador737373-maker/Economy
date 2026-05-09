# menu_bellevue.py

TEMPI = {
    "pizza": 300,
    "primo": 450,
    "secondo": 600,
    "dessert": 180,
    "last_minute": 240
}

MENU_DATI = {
    # --- LE NOSTRE PIZZE ---
    "Margherita": {"ing": {"impasto": 1, "pomodoro": 1, "mozzarella": 1, "basilico": 1}, "tempo": TEMPI["pizza"]},
    "Diavola": {"ing": {"impasto": 1, "pomodoro": 1, "mozzarella": 1, "salame_piccante": 1}, "tempo": TEMPI["pizza"]},
    "Marinara": {"ing": {"impasto": 1, "pomodoro": 1, "aglio": 1, "origano": 1, "olio": 1}, "tempo": TEMPI["pizza"]},
    "Quattro Formaggi": {"ing": {"impasto": 1, "mozzarella": 1, "gorgonzola": 1, "fontina": 1, "parmigiano": 1}, "tempo": TEMPI["pizza"]},
    "Boscaiola": {"ing": {"impasto": 1, "pomodoro": 1, "mozzarella": 1, "funghi": 1, "prosciutto_cotto": 1}, "tempo": TEMPI["pizza"]},
    "Salsicce E Friarielli": {"ing": {"impasto": 1, "mozzarella": 1, "salsiccia": 1, "friarielli": 1}, "tempo": TEMPI["pizza"]},
    "Capricciosa": {"ing": {"impasto": 1, "pomodoro": 1, "mozzarella": 1, "prosciutto_cotto": 1, "funghi": 1, "carciofi": 1, "olive": 1}, "tempo": TEMPI["pizza"]},
    "Wurstel E Patatine": {"ing": {"impasto": 1, "pomodoro": 1, "mozzarella": 1, "wurstel": 1, "patatine_fritte": 1}, "tempo": TEMPI["pizza"]},
    "Frutti Di Mare": {"ing": {"impasto": 1, "pomodoro": 1, "frutti_di_mare": 1, "aglio": 1, "prezzemolo": 1}, "tempo": TEMPI["pizza"]},
    "La Bellevue": {"ing": {"impasto": 1, "pomodoro": 1, "mozzarella": 1, "rucola": 1, "parmigiano": 1, "pomodorini": 1, "bresaola": 1}, "tempo": 360},

    # --- I NOSTRI PRIMI PIATTI ---
    "Pasta Al Ragù": {"ing": {"pasta_fresca": 1, "ragu_carne": 1}, "tempo": TEMPI["primo"]},
    "Penne All'Arrabbiata": {"ing": {"penne": 1, "pomodoro": 1, "aglio": 1, "peperoncino": 1}, "tempo": TEMPI["primo"]},
    "Cacio E Pepe": {"ing": {"pasta": 1, "pecorino_romano": 1, "pepe_nero": 1}, "tempo": TEMPI["primo"]},
    "Spaghetti Alle Vongole": {"ing": {"spaghetti": 1, "vongole": 1, "aglio": 1, "prezzemolo": 1}, "tempo": TEMPI["primo"]},
    "Orecchiette Cime Di Rapa": {"ing": {"orecchiette": 1, "cime_di_rapa": 1, "aglio": 1, "olio": 1}, "tempo": TEMPI["primo"]},
    "Pasta Panna E Tonno": {"ing": {"pasta": 1, "panna": 1, "tonno": 1}, "tempo": TEMPI["primo"]},
    "Pasta Sugo Di Salsiccia": {"ing": {"pasta": 1, "pomodoro": 1, "salsiccia": 1}, "tempo": TEMPI["primo"]},
    "Tortellini In Brodo": {"ing": {"tortellini_carne": 1, "brodo_di_carne": 1}, "tempo": TEMPI["primo"]},
    "Spaghetti Sugo E Polpette": {"ing": {"spaghetti": 1, "pomodoro": 1, "polpette_carne": 1}, "tempo": TEMPI["primo"]},

    # --- I NOSTRI SECONDI PIATTI ---
    "Scaloppine Al Limone": {"ing": {"fettine_carne": 2, "limone": 1}, "tempo": TEMPI["secondo"]},
    "Involtini Pollo E Formaggio": {"ing": {"pollo": 1, "formaggio": 1}, "tempo": TEMPI["secondo"]},
    "Arrosto Di Vitello": {"ing": {"carne_vitello": 1}, "tempo": 900},
    "Filetto Di Maiale In Salsa": {"ing": {"filetto_maiale": 1, "salsa": 1}, "tempo": TEMPI["secondo"]},
    "Pollo Al Lime": {"ing": {"petto_pollo": 1, "lime": 1}, "tempo": TEMPI["secondo"]},
    "Involtini Vitello Nocciole": {"ing": {"fettine_vitello": 1, "nocciole": 1}, "tempo": TEMPI["secondo"]},
    "Finta Pizza Di Albumi": {"ing": {"albumi": 1, "funghi_champignon": 1}, "tempo": TEMPI["last_minute"]},

    # --- I DESSERT ---
    "Tiramisù": {"ing": {"savoiardi": 1, "mascarpone": 1, "caffe": 1}, "tempo": TEMPI["dessert"]},
    "Creme Brulée": {"ing": {"panna": 1, "uova": 2, "zucchero": 1}, "tempo": TEMPI["dessert"]},
    "Mousse Al Cioccolato": {"ing": {"cioccolato": 1, "panna": 1}, "tempo": TEMPI["dessert"]},
    "Puffinglese": {"ing": {"pasta_sfoglia": 1, "crema": 1}, "tempo": TEMPI["dessert"]},
    "Zuppa Inglese": {"ing": {"savoiardi": 1, "alchermes": 1, "crema": 1}, "tempo": TEMPI["dessert"]},
    "Cannoli Siciliani": {"ing": {"cialde_cannolo": 1, "ricotta": 1}, "tempo": TEMPI["dessert"]},
    "Babà Napoletano": {"ing": {"baba_base": 1, "rum": 1}, "tempo": TEMPI["dessert"]},
    "Profitterol": {"ing": {"bigne": 1, "cioccolato": 1, "panna": 1}, "tempo": TEMPI["dessert"]}
}
