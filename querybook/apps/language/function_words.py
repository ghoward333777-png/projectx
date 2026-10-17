"""Closed-class words (articles, pronouns, prepositions, conjunctions, common auxiliaries) per language.

The bundled word lists are content-word dictionaries and leave these out, yet they are the surest sign of
which language a sentence is in. Standard grammar-book material, listed by hand; used for language
identification of transcripts and to mark these words as known.
"""
FUNCTION_WORDS = {
    "en": "the a an and or but of to in on at by for with from is are was were be been am do does did have has had not no it this that these those i you he she we they me him her us them my your his its our their what who which how why when where there here can will would should".split(),
    "es": "el la los las un una unos unas y o pero de del a al en con por para sin es son era fue ser estar está están soy eres somos no sí que qué quién cómo cuándo dónde yo tú él ella nosotros ellos me te se le les lo mi tu su muy más también hay".split(),
    "fr": "le la les un une des et ou mais de du au aux en dans sur avec pour par sans est sont était être avoir ai as a avons ne pas que qui quoi comment quand où je tu il elle nous vous ils elles me te se mon ma mes ton ta son sa ses très plus aussi c'est".split(),
    "de": "der die das den dem des ein eine einen einem und oder aber von zu in im an am auf mit für aus bei nach ist sind war waren sein bin bist haben hat hatte nicht kein keine dass was wer wie wann wo ich du er sie es wir ihr mich dich sich mein dein sehr auch noch schon".split(),
    "it": "il lo la i gli le un uno una e o ma di del della a al in nel con per su da è sono era essere ho ha abbiamo non che chi come quando dove io tu lui lei noi voi loro mi ti si mio mia molto più anche".split(),
    "pt": "o a os as um uma uns umas e ou mas de do da dos das em no na com por para sem é são era ser estar está estou tenho tem não sim que quem como quando onde eu tu ele ela nós eles elas me te se meu minha muito mais também".split(),
    "nl": "de het een en of maar van te in op aan met voor uit bij naar is zijn was waren ben bent heb heeft had niet geen dat wat wie hoe wanneer waar ik jij je hij zij ze wij we jullie mij me zich mijn jouw zeer heel ook nog al".split(),
    "sv": "en ett den det de och eller men av till i på med för från om är var vara har hade inte ingen att vad vem hur när var jag du han hon vi ni dem mig dig sig min din mycket också redan".split(),
    "da": "en et den det de og eller men af til i på med for fra om er var være har havde ikke ingen at hvad hvem hvordan hvornår hvor jeg du han hun vi I dem mig dig sig min din meget også allerede".split(),
    "no": "en et ei den det de og eller men av til i på med for fra om er var være har hadde ikke ingen at hva hvem hvordan når hvor jeg du han hun vi dere dem meg deg seg min din veldig også allerede".split(),
    "fi": "ja tai mutta on ovat oli olla ei en et emme ette eivät että mitä kuka miten milloin missä minä sinä hän me te he minun sinun hänen se ne tämä tuo nämä hyvin myös jo vielä kanssa".split(),
    "pl": "i lub ale z ze w we na do od po przez dla bez jest są był była być mam ma nie tak że co kto jak kiedy gdzie ja ty on ona ono my wy oni one mnie cię się mój moja bardzo też już".split(),
    "cs": "a nebo ale z ze v ve na do od po přes pro bez je jsou byl byla být mám má ne ano že co kdo jak kdy kde já ty on ona ono my vy oni mě tě se můj moje velmi také už".split(),
    "el": "ο η το οι τα ένας μία ένα και ή αλλά του της των σε στο στη στον με για από χωρίς είναι ήταν έχω έχει δεν όχι ναι ότι τι ποιος πώς πότε πού εγώ εσύ αυτός αυτή εμείς εσείς αυτοί μου σου πολύ επίσης".split(),
    "ro": "și sau dar de din la în pe cu pentru fără este sunt era fi am are nu da că ce cine cum când unde eu tu el ea noi voi ei ele mă te se meu mea foarte mai și".split(),
    "hu": "a az egy és vagy de hogy nem igen van vannak volt lenni én te ő mi ti ők engem téged magát mit ki hogyan mikor hol nagyon is már még ez azt ezt".split(),
    "ca": "el la els les un una i o però de del a al en amb per per sense és són era ser estar està no sí que qui com quan on jo tu ell ella nosaltres ells em et es meu meva molt més també hi".split(),
}
INDEX = {}
for _l, _ws in FUNCTION_WORDS.items():
    for _w in _ws:
        INDEX.setdefault(_w.lower(), set()).add(_l)
