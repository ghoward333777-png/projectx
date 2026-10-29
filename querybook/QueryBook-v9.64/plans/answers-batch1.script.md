# the stage performer (new model): answer videos, batch 1

Each line is built from a sourced or computed fact (see answers-batch1.json). The video model only performs it.

## Fixed instructions (paste before every clip)

```
Use the attached image: this exact woman — same face, hair, skin, lips and teeth. Do not change her identity.

Shot: head and shoulders, facing the camera straight on, eyes level with the lens. The camera does not move, zoom or cut. Soft, even, front lighting with no hard shadows across the mouth. Plain, still background. Her whole mouth and chin stay in view the entire time; no hands, hair or objects in front of the face.

Performance: she answers a question, speaking clearly in natural American English at a calm, friendly pace, looking into the camera, with a warm, neutral expression. Natural blinking and small natural head movements only. She says exactly the words given — no extra words, no humming, no music, no other sounds. No captions, subtitles or any text on screen.

Timing: she starts with her lips gently closed for half a second, speaks the line, then closes her lips and holds still for half a second at the end.

She says exactly:
```

## Clips

| Code | Line | Covers |
|---|---|---|
| A01 | "The capital of France is Paris." | Places — What is the capital of France? |
| A02 | "The capital of Japan is Tokyo." | Places — What is the capital of Japan? |
| A03 | "The capital of Australia is Canberra." | Places — What is the capital of Australia? |
| A04 | "The capital of Canada is Ottawa." | Places — What is the capital of Canada? |
| A05 | "The capital of Brazil is Brasília." | Places — What is the capital of Brazil? |
| A06 | "The capital of Italy is Rome." | Places — What is the capital of Italy? |
| A07 | "The capital of Germany is Berlin." | Places — What is the capital of Germany? |
| A08 | "Mount Everest is about 8,849 metres above sea level." | Places — How tall is Mount Everest? |
| A09 | "The Nile is 6,650 kilometres long." | Places — How long is the Nile? |
| A10 | "Kenya is in Africa." | Places — Which continent is Kenya in? |
| A11 | "The currency of Japan is the yen." | Countries — What is the currency of Japan? |
| A12 | "The currency of the United Kingdom is the pound sterling." | Countries — What is the currency of the United Kingdom? |
| A13 | "The official language of Brazil is Portuguese." | Languages — What language is spoken in Brazil? |
| A14 | "The official languages of Canada are English and French." | Languages — What are the official languages of Canada? |
| A15 | "Albert Einstein was born on 14 March 1879, in Ulm." | People — When was Albert Einstein born? |
| A16 | "Marie Curie was born on 7 November 1867, in Warsaw." | People — When was Marie Curie born? |
| A17 | "Martin Luther King Junior was born on 15 January 1929, in Atlanta." | People — When was Martin Luther King Jr. born? |
| A18 | "Nelson Mandela was born on 18 July 1918, in Mvezo." | People — When was Nelson Mandela born? |
| A19 | "Mahatma Gandhi was born on 2 October 1869, in Porbandar." | People — When was Mahatma Gandhi born? |
| A20 | "Wolfgang Amadeus Mozart was born on 27 January 1756, in Salzburg." | People — When was Wolfgang Amadeus Mozart born? |
| A21 | "Charles Darwin was born on 12 February 1809, in Shrewsbury." | People — When was Charles Darwin born? |
| A22 | "Barack Obama was born on 4 August 1961, in Honolulu." | People — When was Barack Obama born? |
| A23 | "Frida Kahlo was born on 6 July 1907, in Mexico City." | People — When was Frida Kahlo born? |
| A24 | "Abraham Lincoln died on 15 April 1865." | People — When did Abraham Lincoln die? |
| A25 | "George Washington was born on 22 February 1732." | People — When was George Washington born? |
| A26 | "The Mona Lisa was painted by Leonardo da Vinci." | Culture — Who painted the Mona Lisa? |
| A27 | "The Starry Night was painted by Vincent van Gogh." | Culture — Who painted The Starry Night? |
| A28 | "Pride and Prejudice was written by Jane Austen, and published on 28 January 1813." | Culture — Who wrote Pride and Prejudice? |
| A29 | "Hamlet was written by William Shakespeare." | Culture — Who wrote Hamlet? |
| A30 | "The film Titanic was directed by James Cameron." | Culture — Who directed the film Titanic? |
| A31 | "World War Two ended on 2 September 1945." | History — When did World War Two end? |
| A32 | "World War One began on 28 July 1914." | History — When did World War One begin? |
| A33 | "Apollo 11 was launched on 16 July 1969." | History — When was Apollo 11 launched? |
| A34 | "The Eiffel Tower is 330 metres tall." | Places — How tall is the Eiffel Tower? |
| A35 | "The Amazon River is 6,400 kilometres long." | Places — How long is the Amazon River? |
| A36 | "The chemical symbol for gold is A, U." | Chemistry — What is the chemical symbol for gold? |
| A37 | "The atomic number of carbon is 6." | Chemistry — What is the atomic number of carbon? |
| A38 | "The chemical formula of water is H two O." | Chemistry — What is the chemical formula of water? |
| A39 | "The chemical symbol for iron is F, E." | Chemistry — What is the chemical symbol for iron? |
| A40 | "The atomic number of oxygen is 8." | Chemistry — What is the atomic number of oxygen? |
| A41 | "A year on Mars lasts about 687 days." | Astronomy — How long is a year on Mars? |
| A42 | "The Moon is, on average, about 385,000 kilometres from Earth." | Astronomy — How far is the Moon from Earth? |
| A43 | "A day on Mars lasts 24.623 hours." | Astronomy — How long is a day on Mars? |
| A44 | "A year on Jupiter lasts about 4,333 days." | Astronomy — How long is a year on Jupiter? |
| A45 | "The square root of 144 is 12." | Mathematics — What is the square root of 144? |
| A46 | "Yes, 97 is a prime number: it has no divisors other than 1 and itself." | Mathematics — Is 97 a prime number? |
| A47 | "A leap year has 366 days." | Time — How many days are in a leap year? |
| A48 | "The first of January 2000 was a Saturday." | Time — What day of the week was 1 January 2000? |
| A49 | "100 degrees Fahrenheit is about 37.8 degrees Celsius." | Units — What is 100 degrees Fahrenheit in Celsius? |
| A50 | "There are 86,400 seconds in a day." | Time — How many seconds are in a day? |
