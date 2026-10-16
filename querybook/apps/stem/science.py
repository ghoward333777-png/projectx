"""Reference data and solvable formulas for science and engineering.

Constants: CODATA 2018 recommended values (NIST); the seven SI defining constants are exact.
Elements: IUPAC conventional/abridged standard atomic weights; for elements with no stable
isotope, the mass number of a long-lived isotope is given in brackets (tables differ for the
heaviest elements — shown as a mass number, never as a measured weight).
Formulas: each can be solved for any of its variables; inputs may carry units ("60 mph").
"""
import math, re
from fractions import Fraction as F

import engine
import units as U

CONSTANTS = [
    # symbol, name, value, unit, exact?, note
    ("c", "speed of light in vacuum", "299792458", "m/s", True, "SI defining constant"),
    ("h", "Planck constant", "6.62607015e-34", "J*s", True, "SI defining constant"),
    ("e", "elementary charge", "1.602176634e-19", "C", True, "SI defining constant"),
    ("k_B", "Boltzmann constant", "1.380649e-23", "J/K", True, "SI defining constant"),
    ("N_A", "Avogadro constant", "6.02214076e23", "1/mol", True, "SI defining constant"),
    ("Δν_Cs", "caesium hyperfine frequency", "9192631770", "Hz", True, "SI defining constant"),
    ("K_cd", "luminous efficacy of 540 THz radiation", "683", "lm/W", True, "SI defining constant"),
    ("R", "molar gas constant", "8.31446261815324", "J/(mol*K)", True, "N_A × k_B (exact)"),
    ("F", "Faraday constant", "96485.33212331001", "C/mol", True, "N_A × e (exact)"),
    ("σ", "Stefan–Boltzmann constant", "5.670374419e-8", "W/(m^2*K^4)", False, "exact in principle; value rounded"),
    ("G", "Newtonian constant of gravitation", "6.67430e-11", "m^3/(kg*s^2)", False, "CODATA 2018, uncertainty 1.5e-15"),
    ("g_n", "standard acceleration of gravity", "9.80665", "m/s^2", True, "defined value"),
    ("atm", "standard atmosphere", "101325", "Pa", True, "defined value"),
    ("m_e", "electron mass", "9.1093837015e-31", "kg", False, "CODATA 2018"),
    ("m_p", "proton mass", "1.67262192369e-27", "kg", False, "CODATA 2018"),
    ("m_n", "neutron mass", "1.67492749804e-27", "kg", False, "CODATA 2018"),
    ("u", "atomic mass constant", "1.66053906660e-27", "kg", False, "CODATA 2018"),
    ("ε0", "vacuum electric permittivity", "8.8541878128e-12", "F/m", False, "CODATA 2018"),
    ("μ0", "vacuum magnetic permeability", "1.25663706212e-6", "N/A^2", False, "CODATA 2018"),
    ("k_e", "Coulomb constant 1/(4πε0)", "8.9875517923e9", "N*m^2/C^2", False, "CODATA 2018"),
    ("α", "fine-structure constant", "7.2973525693e-3", "", False, "CODATA 2018"),
    ("R∞", "Rydberg constant", "10973731.568160", "1/m", False, "CODATA 2018"),
    ("a0", "Bohr radius", "5.29177210903e-11", "m", False, "CODATA 2018"),
]
CONSTANT_SOURCE = "CODATA 2018 recommended values (NIST); SI Brochure 9th edition (2019) for defining constants"

ELEMENTS_RAW = """1 H Hydrogen 1.008;2 He Helium 4.0026;3 Li Lithium 6.94;4 Be Beryllium 9.0122;5 B Boron 10.81;6 C Carbon 12.011;
7 N Nitrogen 14.007;8 O Oxygen 15.999;9 F Fluorine 18.998;10 Ne Neon 20.180;11 Na Sodium 22.990;12 Mg Magnesium 24.305;
13 Al Aluminium 26.982;14 Si Silicon 28.085;15 P Phosphorus 30.974;16 S Sulfur 32.06;17 Cl Chlorine 35.45;18 Ar Argon 39.95;
19 K Potassium 39.098;20 Ca Calcium 40.078;21 Sc Scandium 44.956;22 Ti Titanium 47.867;23 V Vanadium 50.942;24 Cr Chromium 51.996;
25 Mn Manganese 54.938;26 Fe Iron 55.845;27 Co Cobalt 58.933;28 Ni Nickel 58.693;29 Cu Copper 63.546;30 Zn Zinc 65.38;
31 Ga Gallium 69.723;32 Ge Germanium 72.630;33 As Arsenic 74.922;34 Se Selenium 78.971;35 Br Bromine 79.904;36 Kr Krypton 83.798;
37 Rb Rubidium 85.468;38 Sr Strontium 87.62;39 Y Yttrium 88.906;40 Zr Zirconium 91.224;41 Nb Niobium 92.906;42 Mo Molybdenum 95.95;
43 Tc Technetium [98];44 Ru Ruthenium 101.07;45 Rh Rhodium 102.91;46 Pd Palladium 106.42;47 Ag Silver 107.87;48 Cd Cadmium 112.41;
49 In Indium 114.82;50 Sn Tin 118.71;51 Sb Antimony 121.76;52 Te Tellurium 127.60;53 I Iodine 126.90;54 Xe Xenon 131.29;
55 Cs Caesium 132.91;56 Ba Barium 137.33;57 La Lanthanum 138.91;58 Ce Cerium 140.12;59 Pr Praseodymium 140.91;60 Nd Neodymium 144.24;
61 Pm Promethium [145];62 Sm Samarium 150.36;63 Eu Europium 151.96;64 Gd Gadolinium 157.25;65 Tb Terbium 158.93;66 Dy Dysprosium 162.50;
67 Ho Holmium 164.93;68 Er Erbium 167.26;69 Tm Thulium 168.93;70 Yb Ytterbium 173.05;71 Lu Lutetium 174.97;72 Hf Hafnium 178.49;
73 Ta Tantalum 180.95;74 W Tungsten 183.84;75 Re Rhenium 186.21;76 Os Osmium 190.23;77 Ir Iridium 192.22;78 Pt Platinum 195.08;
79 Au Gold 196.97;80 Hg Mercury 200.59;81 Tl Thallium 204.38;82 Pb Lead 207.2;83 Bi Bismuth 208.98;84 Po Polonium [209];
85 At Astatine [210];86 Rn Radon [222];87 Fr Francium [223];88 Ra Radium [226];89 Ac Actinium [227];90 Th Thorium 232.04;
91 Pa Protactinium 231.04;92 U Uranium 238.03;93 Np Neptunium [237];94 Pu Plutonium [244];95 Am Americium [243];96 Cm Curium [247];
97 Bk Berkelium [247];98 Cf Californium [251];99 Es Einsteinium [252];100 Fm Fermium [257];101 Md Mendelevium [258];102 No Nobelium [259];
103 Lr Lawrencium [266];104 Rf Rutherfordium [267];105 Db Dubnium [268];106 Sg Seaborgium [269];107 Bh Bohrium [270];108 Hs Hassium [269];
109 Mt Meitnerium [278];110 Ds Darmstadtium [281];111 Rg Roentgenium [282];112 Cn Copernicium [285];113 Nh Nihonium [286];
114 Fl Flerovium [289];115 Mc Moscovium [290];116 Lv Livermorium [293];117 Ts Tennessine [294];118 Og Oganesson [294]"""
ELEMENT_SOURCE = "IUPAC conventional and abridged standard atomic weights; [n] = mass number of a long-lived isotope"


def _elements():
    out = []
    for item in ELEMENTS_RAW.replace("\n", "").split(";"):
        z, sym, name, w = item.split()
        out.append({"z": int(z), "symbol": sym, "name": name, "weight": w, "stable": not w.startswith("[")})
    return out


ELEMENTS = _elements()
BY_SYMBOL = {e["symbol"]: e for e in ELEMENTS}
BY_NAME = {e["name"].lower(): e for e in ELEMENTS}
BY_NAME["aluminum"] = BY_SYMBOL["Al"]
BY_NAME["cesium"] = BY_SYMBOL["Cs"]


def element(query):
    q = str(query).strip()
    if q.isdigit() and 1 <= int(q) <= len(ELEMENTS):
        return ELEMENTS[int(q) - 1]
    return BY_SYMBOL.get(q) or BY_SYMBOL.get(q.capitalize()) or BY_NAME.get(q.lower())


class FormulaError(Exception):
    pass


def parse_formula(text):
    """'Ca(OH)2' -> {'Ca': 1, 'O': 2, 'H': 2}. Supports nested brackets and hydrates (CuSO4·5H2O)."""
    s = str(text).strip().replace(" ", "").replace("[", "(").replace("]", ")")
    if not s:
        raise FormulaError("type a chemical formula, for example H2O or Ca(OH)2")
    total = {}
    for part in re.split(r"[·.*]", s):
        m = re.match(r"^(\d+)(.*)$", part)
        mult, body = (int(m.group(1)), m.group(2)) if m else (1, part)
        for k, v in _parse_group(body).items():
            total[k] = total.get(k, 0) + v * mult
    return total


def _parse_group(s):
    stack = [{}]
    i = 0
    while i < len(s):
        ch = s[i]
        if ch == "(":
            stack.append({})
            i += 1
        elif ch == ")":
            if len(stack) == 1:
                raise FormulaError("unbalanced brackets")
            i += 1
            m = re.match(r"\d+", s[i:])
            n = int(m.group(0)) if m else 1
            i += len(m.group(0)) if m else 0
            grp = stack.pop()
            for k, v in grp.items():
                stack[-1][k] = stack[-1].get(k, 0) + v * n
        else:
            m = re.match(r"([A-Z][a-z]?)(\d*)", s[i:])
            if not m:
                raise FormulaError("could not read '%s' — element symbols start with a capital letter" % s[i:])
            sym = m.group(1)
            if sym not in BY_SYMBOL:
                raise FormulaError("'%s' is not an element symbol" % sym)
            n = int(m.group(2)) if m.group(2) else 1
            stack[-1][sym] = stack[-1].get(sym, 0) + n
            i += len(m.group(0))
    if len(stack) != 1:
        raise FormulaError("unbalanced brackets")
    return stack[0]


def molar_mass(text):
    counts = parse_formula(text)
    rows, total, approx_iso = [], F(0), False
    for sym, n in counts.items():
        w = BY_SYMBOL[sym]["weight"]
        if w.startswith("["):
            approx_iso = True
            w = w.strip("[]")
        part = F(w) * n
        total += part
        rows.append({"symbol": sym, "name": BY_SYMBOL[sym]["name"], "count": n, "weight": BY_SYMBOL[sym]["weight"], "subtotal": _dec(part)})
    return {"formula": text, "elements": rows, "molar_mass": _dec(total), "unit": "g/mol",
            "note": ("includes a mass number in place of a standard atomic weight" if approx_iso else
                     "sum of standard atomic weights; precision follows the least precise weight used")}


def _dec(fr):
    return engine.describe(fr)["decimal"]


# ----------------------------------------------------------------------------- formulas
# (id, name, field, display, [(var, meaning, SI unit, default or None)], {var: solution}, {constant: value})
FORMULAS = [
    ("ohm", "Ohm's law", "Electricity", "V = I · R", [("V", "voltage", "V", None), ("I", "current", "A", None), ("R", "resistance", "ohm", None)],
     {"V": "I*R", "I": "V/R", "R": "V/I"}, {}),
    ("power_vi", "Electric power", "Electricity", "P = V · I", [("P", "power", "W", None), ("V", "voltage", "V", None), ("I", "current", "A", None)],
     {"P": "V*I", "V": "P/I", "I": "P/V"}, {}),
    ("power_i2r", "Resistive power", "Electricity", "P = I² · R", [("P", "power", "W", None), ("I", "current", "A", None), ("R", "resistance", "ohm", None)],
     {"P": "I**2*R", "I": "sqrt(P/R)", "R": "P/I**2"}, {}),
    ("parallel", "Two resistors in parallel", "Electricity", "R = R1·R2 / (R1 + R2)", [("R", "combined resistance", "ohm", None), ("R1", "first resistor", "ohm", None), ("R2", "second resistor", "ohm", None)],
     {"R": "R1*R2/(R1+R2)", "R1": "R*R2/(R2-R)", "R2": "R*R1/(R1-R)"}, {}),
    ("cap_energy", "Energy stored in a capacitor", "Electricity", "E = ½ · C · V²", [("E", "energy", "J", None), ("Cap", "capacitance", "C/V", None), ("V", "voltage", "V", None)],
     {"E": "Cap*V**2/2", "Cap": "2*E/V**2", "V": "sqrt(2*E/Cap)"}, {}),
    ("coulomb", "Coulomb's law", "Electricity", "F = k_e · q1 · q2 / r²", [("Fc", "force", "N", None), ("q1", "charge 1", "C", None), ("q2", "charge 2", "C", None), ("r", "distance", "m", None)],
     {"Fc": "ke*q1*q2/r**2", "q1": "Fc*r**2/(ke*q2)", "q2": "Fc*r**2/(ke*q1)", "r": "sqrt(ke*q1*q2/Fc)"}, {"ke": "8.9875517923e9"}),
    ("newton2", "Newton's second law", "Mechanics", "F = m · a", [("Fn", "force", "N", None), ("m", "mass", "kg", None), ("a", "acceleration", "m/s^2", None)],
     {"Fn": "m*a", "m": "Fn/a", "a": "Fn/m"}, {}),
    ("weight", "Weight", "Mechanics", "W = m · g", [("W", "weight (force)", "N", None), ("m", "mass", "kg", None), ("g", "gravitational acceleration", "m/s^2", "9.80665")],
     {"W": "m*g", "m": "W/g", "g": "W/m"}, {}),
    ("kinetic", "Kinetic energy", "Mechanics", "E = ½ · m · v²", [("E", "energy", "J", None), ("m", "mass", "kg", None), ("v", "speed", "m/s", None)],
     {"E": "m*v**2/2", "m": "2*E/v**2", "v": "sqrt(2*E/m)"}, {}),
    ("potential", "Gravitational potential energy", "Mechanics", "E = m · g · h", [("E", "energy", "J", None), ("m", "mass", "kg", None), ("g", "gravitational acceleration", "m/s^2", "9.80665"), ("h", "height", "m", None)],
     {"E": "m*g*h", "m": "E/(g*h)", "g": "E/(m*h)", "h": "E/(m*g)"}, {}),
    ("momentum", "Momentum", "Mechanics", "p = m · v", [("p", "momentum", "kg*m/s", None), ("m", "mass", "kg", None), ("v", "velocity", "m/s", None)],
     {"p": "m*v", "m": "p/v", "v": "p/m"}, {}),
    ("work", "Work", "Mechanics", "W = F · d", [("Wk", "work", "J", None), ("Fw", "force", "N", None), ("d", "distance", "m", None)],
     {"Wk": "Fw*d", "Fw": "Wk/d", "d": "Wk/Fw"}, {}),
    ("power", "Power", "Mechanics", "P = W / t", [("P", "power", "W", None), ("Wk", "work or energy", "J", None), ("t", "time", "s", None)],
     {"P": "Wk/t", "Wk": "P*t", "t": "Wk/P"}, {}),
    ("speed", "Average speed", "Motion", "v = d / t", [("v", "speed", "m/s", None), ("d", "distance", "m", None), ("t", "time", "s", None)],
     {"v": "d/t", "d": "v*t", "t": "d/v"}, {}),
    ("suvat1", "Velocity under constant acceleration", "Motion", "v = u + a · t", [("v", "final velocity", "m/s", None), ("u", "initial velocity", "m/s", None), ("a", "acceleration", "m/s^2", None), ("t", "time", "s", None)],
     {"v": "u+a*t", "u": "v-a*t", "a": "(v-u)/t", "t": "(v-u)/a"}, {}),
    ("suvat2", "Velocity and distance", "Motion", "v² = u² + 2 · a · s", [("v", "final velocity", "m/s", None), ("u", "initial velocity", "m/s", None), ("a", "acceleration", "m/s^2", None), ("s", "distance", "m", None)],
     {"v": "sqrt(u**2+2*a*s)", "u": "sqrt(v**2-2*a*s)", "a": "(v**2-u**2)/(2*s)", "s": "(v**2-u**2)/(2*a)"}, {}),
    ("projectile", "Projectile range (level ground)", "Motion", "R = v² · sin(2θ) / g", [("Rg", "range", "m", None), ("v", "launch speed", "m/s", None), ("theta", "launch angle in degrees", "", None), ("g", "gravitational acceleration", "m/s^2", "9.80665")],
     {"Rg": "v**2*sind(2*theta)/g", "v": "sqrt(Rg*g/sind(2*theta))", "theta": "asind(Rg*g/v**2)/2", "g": "v**2*sind(2*theta)/Rg"}, {}),
    ("pendulum", "Simple pendulum period", "Motion", "T = 2π · √(L / g)", [("T", "period", "s", None), ("L", "length", "m", None), ("g", "gravitational acceleration", "m/s^2", "9.80665")],
     {"T": "2*pi*sqrt(L/g)", "L": "g*(T/(2*pi))**2", "g": "L*(2*pi/T)**2"}, {}),
    ("gravity", "Newton's law of gravitation", "Mechanics", "F = G · m1 · m2 / r²", [("Fg", "force", "N", None), ("m1", "mass 1", "kg", None), ("m2", "mass 2", "kg", None), ("r", "distance", "m", None)],
     {"Fg": "G*m1*m2/r**2", "m1": "Fg*r**2/(G*m2)", "m2": "Fg*r**2/(G*m1)", "r": "sqrt(G*m1*m2/Fg)"}, {"G": "6.67430e-11"}),
    ("hooke", "Hooke's law", "Materials", "F = k · x", [("Fk", "force", "N", None), ("k", "spring constant", "N/m", None), ("x", "extension", "m", None)],
     {"Fk": "k*x", "k": "Fk/x", "x": "Fk/k"}, {}),
    ("stress", "Stress", "Materials", "σ = F / A", [("sigma", "stress", "Pa", None), ("Fs", "force", "N", None), ("A", "area", "m^2", None)],
     {"sigma": "Fs/A", "Fs": "sigma*A", "A": "Fs/sigma"}, {}),
    ("young", "Young's modulus", "Materials", "E = σ / ε", [("Ey", "Young's modulus", "Pa", None), ("sigma", "stress", "Pa", None), ("strain", "strain (ΔL/L)", "", None)],
     {"Ey": "sigma/strain", "sigma": "Ey*strain", "strain": "sigma/Ey"}, {}),
    ("density", "Density", "Matter", "ρ = m / V", [("rho", "density", "kg/m^3", None), ("m", "mass", "kg", None), ("Vol", "volume", "m^3", None)],
     {"rho": "m/Vol", "m": "rho*Vol", "Vol": "m/rho"}, {}),
    ("pressure", "Pressure", "Matter", "p = F / A", [("p", "pressure", "Pa", None), ("Fp", "force", "N", None), ("A", "area", "m^2", None)],
     {"p": "Fp/A", "Fp": "p*A", "A": "Fp/p"}, {}),
    ("ideal_gas", "Ideal gas law", "Matter", "p · V = n · R · T", [("p", "pressure", "Pa", None), ("Vol", "volume", "m^3", None), ("n", "amount of substance", "mol", None), ("T", "temperature", "K", None)],
     {"p": "n*Rgas*T/Vol", "Vol": "n*Rgas*T/p", "n": "p*Vol/(Rgas*T)", "T": "p*Vol/(n*Rgas)"}, {"Rgas": "8.31446261815324"}),
    ("heat", "Heat capacity", "Heat", "Q = m · c · ΔT", [("Q", "heat", "J", None), ("m", "mass", "kg", None), ("cp", "specific heat capacity", "J/(kg*K)", None), ("dT", "temperature change", "K", None)],
     {"Q": "m*cp*dT", "m": "Q/(cp*dT)", "cp": "Q/(m*dT)", "dT": "Q/(m*cp)"}, {}),
    ("wave", "Wave speed", "Waves", "v = f · λ", [("v", "wave speed", "m/s", None), ("f", "frequency", "Hz", None), ("lam", "wavelength", "m", None)],
     {"v": "f*lam", "f": "v/lam", "lam": "v/f"}, {}),
    ("photon", "Photon energy", "Waves", "E = h · f", [("E", "energy", "J", None), ("f", "frequency", "Hz", None)],
     {"E": "hP*f", "f": "E/hP"}, {"hP": "6.62607015e-34"}),
    ("mass_energy", "Mass–energy equivalence", "Modern physics", "E = m · c²", [("E", "energy", "J", None), ("m", "mass", "kg", None)],
     {"E": "m*cL**2", "m": "E/cL**2"}, {"cL": "299792458"}),
    ("circle", "Area of a circle", "Geometry", "A = π · r²", [("A", "area", "m^2", None), ("r", "radius", "m", None)],
     {"A": "pi*r**2", "r": "sqrt(A/pi)"}, {}),
    ("pythagoras", "Pythagorean theorem", "Geometry", "c² = a² + b²", [("c", "hypotenuse", "m", None), ("a", "side a", "m", None), ("b", "side b", "m", None)],
     {"c": "sqrt(a**2+b**2)", "a": "sqrt(c**2-b**2)", "b": "sqrt(c**2-a**2)"}, {}),
    ("snell", "Snell's law", "Optics", "n1 · sin θ1 = n2 · sin θ2", [("n1", "refractive index 1", "", None), ("t1", "angle 1 in degrees", "", None), ("n2", "refractive index 2", "", None), ("t2", "angle 2 in degrees", "", None)],
     {"n1": "n2*sind(t2)/sind(t1)", "t1": "asind(n2*sind(t2)/n1)", "n2": "n1*sind(t1)/sind(t2)", "t2": "asind(n1*sind(t1)/n2)"}, {}),
    ("interest", "Compound interest", "Finance", "A = P · (1 + r/n)^(n·t)", [("Amt", "final amount", "", None), ("P", "principal", "", None), ("rate", "annual rate (0.05 = 5%)", "", None), ("n", "compounding periods per year", "", "12"), ("t", "years", "", None)],
     {"Amt": "P*(1+rate/n)**(n*t)", "P": "Amt/(1+rate/n)**(n*t)", "t": "ln(Amt/P)/(n*ln(1+rate/n))"}, {}),
    ("efficiency", "Efficiency", "Engineering", "η = P_out / P_in", [("eta", "efficiency (0–1)", "", None), ("Pout", "output power", "W", None), ("Pin", "input power", "W", None)],
     {"eta": "Pout/Pin", "Pout": "eta*Pin", "Pin": "Pout/eta"}, {}),
    ("torque", "Torque", "Engineering", "τ = F · r", [("Tq", "torque", "N*m", None), ("Ft", "force", "N", None), ("r", "lever arm", "m", None)],
     {"Tq": "Ft*r", "Ft": "Tq/r", "r": "Tq/Ft"}, {}),
]
FORMULA_BY_ID = {f[0]: f for f in FORMULAS}


def formula_list():
    out = []
    for fid, name, field, disp, vars_, sol, consts in FORMULAS:
        out.append({"id": fid, "name": name, "field": field, "equation": disp,
                    "variables": [{"symbol": v, "meaning": m, "unit": u or "(no unit)", "default": d, "solvable": v in sol} for v, m, u, d in vars_],
                    "constants": consts})
    return out


def solve(fid, unknown, given, out_unit=None):
    """Solve formula `fid` for `unknown` from `given` {var: "value [unit]"}."""
    if fid not in FORMULA_BY_ID:
        raise FormulaError("unknown formula")
    _, name, field, disp, vars_, sol, consts = FORMULA_BY_ID[fid]
    if unknown not in sol:
        raise FormulaError("this formula cannot be solved for %s here" % unknown)
    values, used = {}, []
    for v, meaning, unit, default in vars_:
        if v == unknown:
            continue
        raw = str(given.get(v, "") or "").strip() or default
        if raw is None:
            raise FormulaError("enter a value for %s (%s)" % (v, meaning))
        dims = U.parse_unit(unit)[1] if unit else U.NONE
        try:
            si, _ = U.to_si(raw, dims)
        except U.UnitError as e:
            raise FormulaError(str(e))
        values[v] = si
        used.append({"symbol": v, "meaning": meaning, "input": raw, "si": engine.describe(si)["decimal"], "unit": unit})
    for k, val in consts.items():
        values[k] = F(val)
    try:
        result = engine.evaluate_with(sol[unknown], values)
    except engine.CalcError as e:
        raise FormulaError(str(e))
    unit = next(u for v, m, u, d in vars_ if v == unknown)
    meaning = next(m for v, m, u, d in vars_ if v == unknown)
    d = engine.describe(result)
    if d["exact"] and "/" in d["display"] and not d["display"].startswith("≈"):
        d["display"] = "≈ " + engine._fmt_float(float(F(d["value"])))     # measurements read better as decimals
    out = {"formula": name, "equation": disp, "unknown": unknown, "meaning": meaning, "unit": unit or "", "result": d,
           "inputs": used, "constants": consts, "method": "%s = %s" % (unknown, sol[unknown])}
    if out_unit and unit:
        try:
            conv = U.convert_value(F(d["value"]) if d["exact"] else F(float(d["value"])), unit, out_unit)
            out["converted"] = conv["display"]
        except (U.UnitError, ValueError) as e:
            raise FormulaError(str(e))
    return out
