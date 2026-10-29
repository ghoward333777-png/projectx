# QueryBook — the question patterns people ask most

About 460 question patterns, grouped by the 20 keystone domains (`_core/qbkeystone.py`), plus questions about time,
units and QueryBook itself. Each pattern stands for every question of its shape: "When was [person] born?" covers
"When was Albert Einstein born?", "When was Marie Curie born?", and so on.

**Coverage.** These patterns are expected to cover the large majority (an estimated ~90%) of factual questions. That is
an estimate from how factual questions are usually distributed, not a measurement: QueryBook's own query log will
measure it once people use it. Exact questions follow a long tail, so no list of a few hundred *exact* questions covers 90%.

**Marks.**
- ⏱ the answer changes often (live or yearly data): answer from the current facts, not from a pre-made video.
- 🧮 computed by QueryBook from rules (no source needed beyond the rule).
- Unmarked: a stable fact — the best candidates for pre-made answer videos (exemplars).

Each section names the sources QueryBook answers it from.

---

## 1. Mathematics 🧮
*Answered from: QueryBook's own computation (STEM application).*

1. What is [x] plus / minus / times / divided by [y]? 🧮
2. What is [p] percent of [n]? 🧮
3. What is the square root of [n]? 🧮
4. What is [n] to the power of [m]? 🧮
5. Is [n] a prime number? 🧮
6. What are the factors of [n]? 🧮
7. What is the greatest common divisor / least common multiple of [a] and [b]? 🧮
8. What is [fraction] as a decimal / percentage? 🧮
9. What is [n] in Roman numerals / binary / hexadecimal? 🧮
10. What is the average / median of [numbers]? 🧮
11. Solve [equation] for x. 🧮
12. What is the derivative / integral of [function]? 🧮
13. What is the area / volume of a [shape] with [dimensions]? 🧮
14. What is the formula for the area / volume of a [shape]?
15. What is the value of pi / e?
16. What is the Pythagorean theorem?
17. How many degrees are in a [triangle / circle / right angle]?
18. What is a [mathematical term]? (e.g. a prime, a logarithm)
19. Who proved / discovered [theorem]?
20. How many zeros are in a [million / billion / trillion]?

## 2. Scientific concepts
*Answered from: Wikidata, OpenAlex (literature), STEM reference tables.*

21. What is [scientific concept]? (e.g. photosynthesis, gravity)
22. How does [natural process] work?
23. What causes [phenomenon]? (e.g. rainbows, tides, seasons, earthquakes)
24. Why is the sky blue?
25. What is the speed of light / sound?
26. What is the boiling / freezing point of water?
27. What is absolute zero?
28. What are the states of matter?
29. What is the value of [constant]? (e.g. Avogadro's number, Planck's constant)
30. What is the SI unit of [quantity]?
31. What is the difference between [concept A] and [concept B]?
32. What is the theory of [relativity / evolution / …]?
33. What are the laws of [motion / thermodynamics]?
34. Who discovered [discovery]?
35. When was [discovery] made?
36. What did [scientist] discover?
37. Who wrote [scientific paper]? When was it published?
38. What is the half-life of [isotope]?
39. What is DNA / RNA / a gene?
40. What is the scientific method?

## 3. Technology and computing
*Answered from: Wikidata, DBLP, SEC filings.*

41. What is [technology]? (e.g. blockchain, cloud computing)
42. Who invented [invention]?
43. When was [invention] invented?
44. When was [product / software] released?
45. What is the latest version of [software]? ⏱
46. Who created [programming language]?
47. What programming language is [software] written in?
48. What does [acronym] stand for? (e.g. HTML, CPU, USB)
49. How many bytes are in a [kilobyte / megabyte / gigabyte]?
50. What is the difference between [RAM] and [storage]? (any two technologies)
51. How does [the internet / Wi-Fi / GPS] work?
52. What is the fastest supercomputer? ⏱
53. Who founded [technology company]?
54. Who is the CEO of [technology company]? ⏱
55. When was [website] launched?
56. Which company makes [product]?
57. What is [algorithm]? (e.g. binary search)
58. What is Moore's law?
59. What is open-source software?
60. What is the most used [browser / operating system / programming language]? ⏱

## 4. Languages
*Answered from: the Language Builder (dictionary, Tatoeba sentences), Wikidata.*

61. What does [word] mean?
62. How do you spell [word]?
63. How do you pronounce [word]?
64. What is a synonym / antonym of [word]?
65. How do you say [phrase] in [language]?
66. Translate [sentence] into [language].
67. What is the [language] word for [thing]?
68. Use [word] in a sentence.
69. What is the plural / past tense of [word]?
70. Is [word] a noun, a verb or an adjective?
71. What is the origin of [word]?
72. What does [idiom] mean?
73. What does [abbreviation] stand for?
74. What rhymes with [word]?
75. How many syllables are in [word]?
76. Is it [form A] or [form B]? (e.g. affect / effect)
77. How do you greet someone in [language]?
78. What language is spoken in [country]?
79. What are the official languages of [country]?
80. How many people speak [language]?
81. What is the most spoken language in the world?
82. What alphabet / script does [language] use?
83. How many letters are in the [language] alphabet?
84. What language family does [language] belong to?
85. Where is [language] spoken?

## 5. Places and geography
*Answered from: Wikidata, USGS GNIS, NOAA, Census.*

86. What is the capital of [country / state]?
87. Where is [place]?
88. What country is [city] in?
89. What county / state is [town] in?
90. What is the population of [place]? ⏱
91. What is the area of [place]?
92. Which continent is [country] in?
93. What countries border [country]?
94. What is the largest / smallest [country / city / lake / desert] in [region]?
95. What is the largest city in [country / state]?
96. What is the highest mountain in [region]?
97. How tall is [mountain]?
98. What is the longest river in [region]?
99. How long is [river]?
100. What is the deepest [lake / ocean / point on Earth]?
101. What ocean / sea is [place] on?
102. What are the coordinates / elevation of [place]?
103. How far is [place A] from [place B]? 🧮
104. What time zone is [place] in?
105. What is the climate of [place] in [month]? (long-term averages)
106. What is the highest / lowest temperature ever recorded in [place]?
107. What are the states / provinces of [country]?
108. How many countries are there in [continent / the world]?
109. What landmarks are in [place]?
110. What is the ZIP / postal code of [place]?

## 6. People
*Answered from: Wikidata, Library of Congress, MusicBrainz, OpenAlex.*

111. Who is / was [person]?
112. When was [person] born?
113. Where was [person] born?
114. How old is [person]? 🧮
115. Is [person] still alive? ⏱
116. When did [person] die?
117. Where did [person] die?
118. How did [person] die? (cause of death)
119. What is [person]'s nationality?
120. What is [person]'s occupation?
121. What is [person] known for? (notable works)
122. What is [person]'s full / real name?
123. Who is / was [person] married to?
124. Who are [person]'s parents / children / siblings?
125. How tall is [person]?
126. Where did [person] study?
127. What awards has [person] won?
128. What positions has [person] held?
129. Who came before / after [person] in [office]?
130. Who was the [nth] president of [country]?
131. Who is the current [office] of [place]? ⏱
132. When did [person] become [office]?
133. What books did [author] write?
134. What films has [actor] been in?
135. What albums / songs did [musician] release?
136. What team does [athlete] play for? ⏱
137. What languages did [person] speak?
138. What was [person]'s religion?
139. Which famous people were born on [date]?
140. Which famous people were born in [place]?

## 7. Events and history
*Answered from: Wikidata, the calendar scaffold, recurring-event slots, the harvest teams' sources.*

141. When did [event] happen?
142. Where did [event] take place?
143. What happened in [year]?
144. What happened on [date] in history?
145. What caused [event]?
146. Who was involved in [event]?
147. How many people died in [disaster / war]?
148. When did [war] start and end?
149. Who won [war / battle]?
150. When was [treaty / document] signed?
151. When did [country] gain independence?
152. Who led [country] in [year]?
153. When was [empire / dynasty] founded? When did it end?
154. When was [historical period]? (e.g. the Renaissance)
155. When was [building / landmark] built?
156. When was [law / amendment] passed?
157. Who assassinated [person]?
158. When did humans first land on the Moon?
159. Who won the [year] [election]? What were the results?
160. When is the next [election] in [place]? ⏱
161. Who won the Nobel Prize in [field] in [year]?
162. Who won the [year] [Super Bowl / World Cup / World Series / final]?
163. Who won Best Picture in [year]?
164. Where were the [year] Olympic Games held?
165. When are the next Olympic Games / World Cup? 
166. When is [holiday] in [year]? 🧮
167. What day of the week was / is [date]? 🧮
168. How many days until [date / holiday]? 🧮⏱
169. When is Easter in [year]? 🧮
170. What is the latest news about [topic]? ⏱

## 8. Living things
*Answered from: NCBI Taxonomy, ITIS, Wikidata.*

171. What is a [species]?
172. What is the scientific name of [species]?
173. What family / order / class does [species] belong to?
174. Where does [species] live?
175. What does [animal] eat?
176. How long does [animal] live?
177. How big / heavy does [animal] get?
178. Is [species] endangered? (conservation status)
179. When did [extinct species] go extinct?
180. Is [plant / mushroom] poisonous?
181. What is the largest / fastest / smallest [kind of animal]?
182. How many legs does [animal] have?
183. How long is [animal]'s pregnancy?
184. What is a baby [animal] called?
185. What is a group of [animals] called?
186. How many species of [group] are there?
187. Are [species A] and [species B] related?
188. How many chromosomes does [species] have?
189. What is the national animal / flower of [country]?
190. When does [plant] bloom?

## 9. Countries and states
*Answered from: Wikidata, World Bank-style official statistics, Census.*

191. What is the currency of [country]?
192. Who is the head of state / head of government of [country]? ⏱
193. What type of government does [country] have?
194. What is the national anthem / motto of [country]?
195. What does the flag of [country] look like?
196. When was [country] founded?
197. What is the GDP / GDP per person of [country]? ⏱
198. What is the life expectancy in [country]? ⏱
199. What is the unemployment / literacy rate in [country]? ⏱
200. What is the largest ethnic group in [country]?
201. What is the main religion in [country]?
202. What is the international calling code / internet domain of [country]?
203. Which side of the road does [country] drive on?
204. What is the national holiday of [country]?
205. How many states / provinces / regions does [country] have?
206. Is [country] a member of [EU / NATO / UN / …]?
207. When did [country] join [organisation]?
208. What is the voting age in [country]?
209. What is the time difference between [country A] and [country B]? 🧮
210. What was [country] called before?

## 10. Law and government
*Answered from: Wikidata, US federal sources (public domain), Census.*

211. What does the [nth] amendment / [article] say?
212. What are the three branches of government?
213. How is the [president / prime minister] chosen?
214. What are the requirements to become [office]?
215. How long is a term for [office]?
216. How many members are in [legislature]?
217. Who are the senators / representatives for [state / district]? ⏱
218. Who is the governor of [state]? ⏱
219. Who is the mayor of [city]? ⏱
220. Who are the justices of [court]? ⏱
221. What was decided in [court case]?
222. When was [law] enacted?
223. What does [legal term] mean?
224. How many electoral votes does [state] have?
225. What is the minimum wage in [place]? ⏱
226. What is the legal drinking / driving age in [place]?
227. What is the sales tax / income tax rate in [place]? ⏱
228. When is the next [election] in [place]? ⏱
229. Who represents [place] in [legislature]? ⏱
230. What is the [constitution] of [country]? When was it adopted?

## 11. Organisations
*Answered from: Wikidata, SEC EDGAR, OpenAlex (institutions), MusicBrainz (labels).*

231. What is [organisation]?
232. When was [organisation] founded?
233. Who founded [organisation]?
234. Where is [organisation] headquartered?
235. Who leads [organisation]? ⏱
236. How many employees does [company] have? ⏱
237. What is [company]'s revenue? ⏱
238. What is [company]'s stock ticker?
239. What does [company] make / sell?
240. Who owns [company / brand]? ⏱
241. What are [company]'s subsidiaries? ⏱
242. When did [company] go public?
243. What is the website of [organisation]?
244. How many members does [organisation] have? ⏱
245. When was [university] founded?
246. How many students does [university] have? ⏱
247. What universities are in [place]?
248. What league is [team] in?
249. How many championships has [team] won?
250. Where does [team] play?

## 12. Culture and the arts
*Answered from: Wikidata, MusicBrainz, Library of Congress, museum open access (Cleveland Museum of Art), MIT OCW.*

251. Who wrote [book]?
252. When was [book / film / song] published / released?
253. Who directed [film]?
254. Who starred in [film / show]?
255. Who sang / wrote [song]?
256. Who composed [music]?
257. Who painted / made [artwork]?
258. Where is [artwork] displayed?
259. What genre is [work]?
260. What is [book / film] about? (its main subject)
261. What is the sequel / prequel to [work]?
262. How many seasons / episodes does [show] have?
263. How long is [film]?
264. What language was [work] originally in?
265. What awards did [work] win?
266. Who won [award] for [category] in [year]?
267. What is the highest-grossing film / best-selling book / album?
268. What instrument does [musician] play?
269. What band was [musician] in?
270. When did [band] form / split up?
271. Who illustrated / translated [book]?
272. What is the ISBN of [book]?
273. Who designed [building]?
274. When is [festival] held?
275. What courses does MIT offer on [subject]? (OpenCourseWare catalog)

## 13. Physics
*Answered from: STEM reference tables, QueryBook computation.*

276. What is the formula for [force / energy / power / …]?
277. What is Newton's [first / second / third] law?
278. What is the acceleration due to gravity?
279. What is the gravitational constant?
280. What is E = mc²?
281. What is the unit of [force / energy / power]?
282. Convert [value] [unit] to [unit]. 🧮
283. What is [physics concept]? (e.g. entropy, quantum entanglement)
284. What is the mass / charge of [particle]?
285. What are the four fundamental forces?
286. What is the speed of sound in [medium]?
287. What is the wavelength of [colour]?
288. How much would [mass] weigh on [planet]? 🧮
289. What is the escape velocity of [planet]?
290. What is Ohm's law?
291. Who discovered [particle / effect]?
292. What is the temperature of the Sun?
293. What is the difference between mass and weight?
294. What is the speed of [object]?
295. How does [device] work? (the physics of it)

## 14. Chemistry and materials
*Answered from: PubChem, openFDA (substances), STEM element tables.*

296. What is the chemical symbol for [element]?
297. What is the atomic number of [element]?
298. What is the atomic mass of [element]?
299. What group / period is [element] in?
300. Is [element] a metal?
301. What is the electron configuration of [element]?
302. Who discovered [element]? What is it named after?
303. How many elements are there?
304. What are the noble gases / halogens / …?
305. What is the chemical formula of [compound]?
306. What is the molar mass of [compound]?
307. What elements are in [compound]?
308. What is the melting / boiling point of [substance]?
309. What is the density of [substance]?
310. What is the pH of [substance]? Is it an acid or a base?
311. Is [substance] soluble in water?
312. Is [chemical] toxic? What are its hazards?
313. What is [compound] used for?
314. What is the common name of [chemical name]?
315. What is the CAS number / InChIKey of [compound]?
316. What is the structure / SMILES of [compound]?
317. What is the valence of [element]?
318. What are the isotopes of [element]?
319. Balance the equation [reaction]. 🧮
320. What happens when [substance A] reacts with [substance B]?

## 15. Medicine and health
*Answered from: NCBI Gene, openFDA, Wikidata. QueryBook gives facts with sources, never personal medical advice.*

321. What is [disease]?
322. What are the symptoms of [disease]?
323. What causes [disease]?
324. How is [disease] treated?
325. Is [disease] contagious?
326. What is the incubation period of [disease]?
327. How common is [disease]? ⏱
328. What gene is linked to [disease]?
329. What is [drug] used for?
330. What are the side effects of [drug]?
331. What is the active ingredient of [drug]?
332. What is the generic name of [brand drug]?
333. When was [drug] approved?
334. Has [drug / product] been recalled? ⏱
335. Who discovered [treatment / vaccine]?
336. What does [organ] do?
337. How many bones / muscles are in the human body?
338. What is a normal [blood pressure / heart rate / body temperature]?
339. What is the BMI for [height] and [weight]? 🧮
340. What blood types are there?
341. What is the difference between a virus and a bacterium?
342. What does [medical term] mean?
343. What vaccines are recommended at [age]? ⏱
344. What is [vitamin / mineral] good for?
345. How much sleep / water does an adult need?

## 16. Economics and finance
*Answered from: BLS, Census, SEC EDGAR, official statistics.*

346. What is the inflation rate in [country]? ⏱
347. What is the unemployment rate in [place]? ⏱
348. What is the GDP growth of [country]? ⏱
349. What is the interest rate set by [central bank]? ⏱
350. Who leads [central bank]? ⏱
351. What is the exchange rate from [currency A] to [currency B]? ⏱
352. What is the price of [gold / oil / commodity]? ⏱
353. What is the value of [stock index]? ⏱
354. What is [company]'s stock price / market value? ⏱
355. What is the national debt of [country]? ⏱
356. What is the median household income in [place]? ⏱
357. What is the poverty rate in [place]? ⏱
358. What is the average pay for [occupation] in [place]? ⏱
359. What is the consumer price index? ⏱
360. What are the largest economies in the world? ⏱
361. What does [economic term] mean? (e.g. inflation, recession)
362. When was [recession / crash]?
363. What is the compound interest on [amount] at [rate] for [years]? 🧮
364. Which tax bracket is [income] in? ⏱
365. What is the price of [cryptocurrency]? ⏱

## 17. Astronomy and space
*Answered from: Wikidata, the calendar scaffold (equinoxes, solstices), QueryBook computation.*

366. How far is [planet / star] from Earth / the Sun?
367. How big is [planet / star]?
368. How many moons does [planet] have?
369. What is the temperature on [planet]?
370. How long is a day / year on [planet]?
371. What is the gravity on [planet]?
372. How many planets are in the Solar System?
373. What is the closest star?
374. What is the brightest star?
375. What constellation is [star] in?
376. How old is the universe / the Earth / the Sun?
377. What is a [black hole / nebula / galaxy]?
378. Who was the first person in space / on the Moon?
379. When was [space mission] launched?
380. When is the next [solar / lunar eclipse]? 🧮
381. When is the next [equinox / solstice]? 🧮
382. What phase is the Moon in on [date]? 🧮
383. When is sunrise / sunset in [place] on [date]? 🧮
384. When is the next [meteor shower / full moon]? 🧮
385. How many people are in space right now? ⏱

## 18. Products and objects
*Answered from: Wikidata, openFDA (devices), SEC filings.*

386. What is [product]?
387. Who makes [product]?
388. When was [product] released?
389. Where is [product] made?
390. What brand owns [product]?
391. What are the dimensions / weight of [product]?
392. What is [object] made of?
393. How does [object] work?
394. What is the latest model of [product line]? ⏱
395. What is the difference between [model A] and [model B]?
396. Has [product] been recalled? ⏱
397. What is the battery life of [device]?
398. How long does [product] usually last?
399. What size is a standard [paper sheet / bed / …]?
400. How much does [product] cost? ⏱
401. Who invented [object]?

## 19. Food and agriculture
*Answered from: USDA FoodData Central, Wikidata, official crop statistics.*

402. How many calories are in [food]?
403. How much protein / sugar / fat / fibre is in [food]?
404. What vitamins and minerals are in [food]?
405. How much caffeine is in [drink]?
406. What is the glycemic index of [food]?
407. Is [food] gluten-free / vegan?
408. What are the ingredients of [dish]?
409. Where does [dish / food] come from?
410. What is the national dish of [country]?
411. What temperature should [meat] be cooked to?
412. How long does [food] keep?
413. When is [fruit / vegetable] in season?
414. What is the scientific name of [crop]?
415. Which country produces the most [crop]? ⏱
416. How much [crop] does [country] produce? ⏱
417. How much water does [crop] need?
418. Is [food] safe for [dogs / cats]?
419. How many [cups / grams] are in a [unit]? 🧮
420. What is [cooking term]?
421. What is the shelf life of [food] once opened?

## 20. Transport
*Answered from: Wikidata, official transport data.*

422. How far is [place A] from [place B] by road / air? 🧮
423. How long is the flight from [place A] to [place B]?
424. What airport serves [city]?
425. What is the code of [airport]?
426. What is the busiest airport in [region]? ⏱
427. What is the fastest [train / car / plane]?
428. What is the top speed of [vehicle]?
429. What is the range / fuel economy of [vehicle model]?
430. Who makes [aircraft / vehicle]?
431. How many passengers does [aircraft] hold?
432. How long is [bridge / tunnel]?
433. When was [bridge / railway / road] built?
434. What is the longest [road / railway / bridge]?
435. When were the first [car / flight / railway]?
436. What lines serve [station]?
437. What is the speed limit on [road type] in [place]?
438. What does [road sign] mean?
439. When did [airline / railway] start?
440. What is the railway gauge in [country]?

## 21. Time, dates and units 🧮
*Answered from: QueryBook computation and the calendar scaffold.*

441. What time is it in [place]? 🧮⏱
442. What is today's date / day of the week? 🧮⏱
443. How many days are there between [date] and [date]? 🧮
444. What date is [n] days after / before [date]? 🧮
445. How old is someone born on [date]? 🧮
446. Convert [value] [unit] to [unit]. (length, weight, volume, area, speed) 🧮
447. What is [n] °F in °C? 🧮
448. How many [unit] are in a [unit]? 🧮
449. Is [year] a leap year? 🧮
450. What week number is [date]? 🧮

## 22. Questions about QueryBook and its facts
*Answered from: the Commons (evidence, status, sources) and the Self-Knowledge Layer.*

451. Is it true that [claim]?
452. What is the source for [fact]?
453. How sure is QueryBook that [fact]? (its status and evidence)
454. What does QueryBook know about [topic]?
455. What changed recently about [topic]? ⏱
456. Do sources disagree about [fact]?
457. What is the difference between [thing A] and [thing B]?
458. What is the biggest / oldest / first [category]?
459. How many [things] are there in [group]?
460. List all [category] in [place]. (e.g. US presidents, planets)
461. What can QueryBook answer? / How does QueryBook work?

---

## Using the list for answer videos (exemplars)

- **Best for pre-made answer videos:** stable patterns with a specific, often-asked filling. For example: the
  capital of each country, when well-known people were born, element symbols, planet facts, how many bones are in the
  human body.
- **Not for pre-made videos:** ⏱ patterns, where the answer changes. QueryBook's own renderer speaks them from the
  current facts.
- **🧮 patterns** need no video per question: one clip per pattern type is enough to teach delivery, and QueryBook
  computes the numbers.
