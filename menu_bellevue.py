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
    "Margherita": {"desc": "Impasto, pomodoro, mozzarella, basilico", "tempo": TEMPI["pizza"]},
    "Diavola": {"desc": "Impasto, pomodoro, mozzarella, salame piccante", "tempo": TEMPI["pizza"]},
    "Marinara": {"desc": "Impasto, pomodoro, aglio, origano, olio", "tempo": TEMPI["pizza"]},
    "Quattro Formaggi": {"desc": "Impasto, mozzarella, gorgonzola, fontina, parmigiano", "tempo": TEMPI["pizza"]},
    "Boscaiola": {"desc": "Impasto, pomodoro, mozzarella, funghi, prosciutto cotto", "tempo": TEMPI["pizza"]},
    "Salsicce E Friarielli": {"desc": "Impasto, mozzarella, salsiccia, friarielli", "tempo": TEMPI["pizza"]},
    "Capricciosa": {"desc": "Impasto, pomodoro, mozzarella, prosciutto cotto, funghi, carciofi, olive", "tempo": TEMPI["pizza"]},
    "Wurstel E Patatine": {"desc": "Impasto, pomodoro, mozzarella, wurstel, patatine fritte", "tempo": TEMPI["pizza"]},
    "Frutti Di Mare": {"desc": "Impasto, pomodoro, frutti di mare, aglio, prezzemolo", "tempo": TEMPI["pizza"]},
    "La Bellevue": {"desc": "Impasto, pomodoro, mozzarella, rucola, parmigiano, pomodorini, bresaola", "tempo": 360},

    # --- I NOSTRI PRIMI PIATTI ---
    "Pasta Al Ragù": {"desc": "Pasta fresca, ragù di carne", "tempo": TEMPI["primo"]},
    "Penne All'Arrabbiata": {"desc": "Penne, pomodoro, aglio, peperoncino", "tempo": TEMPI["primo"]},
    "Cacio E Pepe": {"desc": "Pasta, pecorino romano, pepe nero", "tempo": TEMPI["primo"]},
    "Spaghetti Alle Vongole": {"desc": "Spaghetti, vongole, aglio, prezzemolo", "tempo": TEMPI["primo"]},
    "Orecchiette Cime Di Rapa": {"desc": "Orecchiette, cime di rapa, aglio, olio", "tempo": TEMPI["primo"]},
    "Pasta Panna E Tonno": {"desc": "Pasta, panna, tonno", "tempo": TEMPI["primo"]},
    "Pasta Sugo Di Salsiccia": {"desc": "Pasta, pomodoro, salsiccia", "tempo": TEMPI["primo"]},
    "Tortellini In Brodo": {"desc": "Tortellini di carne, brodo di carne", "tempo": TEMPI["primo"]},
    "Spaghetti Sugo E Polpette": {"desc": "Spaghetti, pomodoro, polpette di carne", "tempo": TEMPI["primo"]},

    # --- I NOSTRI SECONDI PIATTI ---
    "Scaloppine Al Limone": {"desc": "Fettine di carne, limone", "tempo": TEMPI["secondo"]},
    "Involtini Pollo E Formaggio": {"desc": "Pollo, formaggio", "tempo": TEMPI["secondo"]},
    "Arrosto Di Vitello": {"desc": "Carne di vitello", "tempo": 900},
    "Filetto Di Maiale In Salsa": {"desc": "Filetto di maiale, salsa", "tempo": TEMPI["secondo"]},
    "Pollo Al Lime": {"desc": "Petto di pollo, lime", "tempo": TEMPI["secondo"]},
    "Involtini Vitello Nocciole": {"desc": "Fettine di vitello, nocciole", "tempo": TEMPI["secondo"]},
    "Finta Pizza Di Albumi": {"desc": "Albumi, funghi champignon", "tempo": TEMPI["last_minute"]},

    # --- I DESSERT ---
    "Tiramisù": {"desc": "Savoiardi, mascarpone, caffè", "tempo": TEMPI["dessert"]},
    "Creme Brulée": {"desc": "Panna, uova, zucchero", "tempo": TEMPI["dessert"]},
    "Mousse Al Cioccolato": {"desc": "Cioccolato, panna", "tempo": TEMPI["dessert"]},
    "Puffinglese": {"desc": "Pasta sfoglia, crema", "tempo": TEMPI["dessert"]},
    "Zuppa Inglese": {"desc": "Savoiardi, alchermes, crema", "tempo": TEMPI["dessert"]},
    "Cannoli Siciliani": {"desc": "Cialde cannolo, ricotta", "tempo": TEMPI["dessert"]},
    "Babà Napoletano": {"desc": "Babà base, rum", "tempo": TEMPI["dessert"]},
    "Profitterol": {"desc": "Bignè, cioccolato, panna", "tempo": TEMPI["dessert"]}
}
