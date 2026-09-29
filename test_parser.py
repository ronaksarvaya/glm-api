import re

def extract_passport_back(text):
    upper = text.upper()
    lines = [line.strip() for line in upper.splitlines() if line.strip()]

    result = {
        "father_name": None,
        "mother_name": None,
        "spouse_name": None,
        "address": None
    }

    def normalize_label(s):
        s = s.lower()
        s = re.sub(r"[^a-z0-9\s]", "", s)
        return re.sub(r"\s+", " ", s).strip()

    father_label_re = re.compile(r"\b(father|fathcr|guarda|guardian)\b")
    mother_label_re = re.compile(r"\b(mother|mothcr)\b")
    spouse_label_re = re.compile(r"\b(spouse)\b")
    address_label_re = re.compile(r"\b(address|addres|aaeens|acres|adress)\b")

    def find_name_after_label(label_re):
        for i, line in enumerate(lines):
            norm = normalize_label(line)
            if label_re.search(norm):
                for j in range(1, 3):
                    if i + j < len(lines):
                        candidate = lines[i + j]
                        c_norm = normalize_label(candidate)
                        
                        if len(c_norm) < 3:
                            continue
                            
                        if label_re != father_label_re and father_label_re.search(c_norm):
                            break
                        if label_re != mother_label_re and mother_label_re.search(c_norm):
                            break
                        if label_re != spouse_label_re and spouse_label_re.search(c_norm):
                            break
                        if address_label_re.search(c_norm):
                            break
                            
                        if re.search(r"\b(road|distt|pin|sector|house|nagar|colony|marg|street)\b", c_norm):
                            break
                            
                        return candidate
                break
        return None

    result["father_name"] = find_name_after_label(father_label_re)
    result["mother_name"] = find_name_after_label(mother_label_re)
    result["spouse_name"] = find_name_after_label(spouse_label_re)

    address_lines = []
    found_address = False
    for line in lines:
        norm = normalize_label(line)
        if not found_address:
            if address_label_re.search(norm):
                found_address = True
            continue
            
        if re.search(r"\b(old\s*passport|file\s*no|date\s*and\s*place|passport\s*no|file\s*to)\b", norm):
            break
        if re.search(r"\b(petpet|mace|dotan pace|ferfes|cer ei|ater me|aeraie)\b", norm):
            break
        if re.fullmatch(r"[a-z0-9\$]{12,16}", norm.replace(" ", "")):
            break
        if re.search(r"\d{2}/\d{2}/\d{4}", line):
            break
            
        address_lines.append(line)
        
    if address_lines:
        result["address"] = " ".join(address_lines).strip()

    return result

test_cases = [
    """Ren / wrph sftrayes &1 a / Name of Father / Legal Guardian 3647377
ASIM GHOSH

EN BI AH / Name of Mother

MUNMUN GHOSH

GR a Get & AF / Name of Spouse

Wall / Address
JALANGI ROAD,SHIV SHAKTI SERVICE STATION

PANCHANANTALA,COSSIMBAZAR ,MURSHIDABAD

PIN:742102,WEST BENGAL,INDIA

Gert aeraie ar a, athe gers Gre wis HY ferfes cer eI / Old Passport No. with Date and Place of Issue
13567791 08/05/2019 KOLKATA

vada 4 / File to.

A1076355662324""",
    """HERA KE

aT HY Nari of Father / Legal Guarda ws081762

ABDUL SATAR NAJAR
ALOE Name of Mother

WASNAZA BANOO
POT WH rere sco

me Aaeens
PUMBAT

DISTT, KULGAM

PIN:192231,JAMMU ANDO KASHMIR, INDIA
TOE a. 4 pre HH +1 Old ua th ine Mace.

ater (Me.

$6106791326787""",
    """I a ileal la baat aia nat ae hes te. tae oll
cemeeeeemone ENED ERI
SANJAY KUMAR
seve er rare at esi .
SINNY KUMAR fees
EL RY Rete Somme .

aT acres
MOUSE NO, #35

SECTOR 22P~A, CHAMDIGARH

Pitts 140027 ,CHANDIGARH, EMETA

JF red al Far a lle NOU Petpet A Dotan Pace ct
46033616 26/44/2040 CHANDIGARH
Wg fte the

CHLOTSS1S4A2419"""
]

for t in test_cases:
    print(extract_passport_back(t))
