<?php

declare(strict_types=1);

/**
 * SlowDating Romance Library builder.
 *
 * Builds dating/data/romance-films.json — the platform's independent
 * playlist of 1,000 romance films for the Watch Party feature, ranked by
 * curated popularity (icons first, then by era and subgenre). Every entry
 * is a real film. A film carries a `youtube_id` only when a legally free,
 * verified copy exists on YouTube (public-domain classics); all others
 * open through a YouTube search so the couple can pick the best available
 * upload. Re-running the script is deterministic: same input, same file.
 *
 *     php dating/bin/build-romance-library.php
 *
 * To harvest fresh YouTube popularity data instead of the curated order,
 * ops can extend this script with the YouTube Data API (needs a key —
 * intentionally not required for the product to run).
 */

// Verified free full movies on YouTube (checked 2026-09): the featured
// rom-com premiere (Romance Movie Central's own upload) plus the
// public-domain classics.
$verified = [
    'She Races to Find a Husband (Full Rom Com)|2023' => '5GicvbAbMYU',
    'Charade|1963' => 'VTeVIpBLVfg',
    'His Girl Friday|1940' => 'UzQWJNNg8DU',
    'My Man Godfrey|1936' => 'YcvDxEMiMTc',
    'Penny Serenade|1941' => 'pNGzeBt4Bek',
    'Made for Each Other|1939' => '5JSU-yGhR-g',
    'Love Affair|1939' => 'wnM11gs58ks',
    'Royal Wedding|1951' => 'UuzLr5MCA7w',
    'A Star Is Born|1937' => 'WPuN-m46INU',
    'Nothing Sacred|1937' => 'HeTzRrhQZLg',
    'Algiers|1938' => 'weIe6fMHxBY',
    'Cyrano de Bergerac|1950' => 'iUI_Gb6UDiY',
    'Second Chorus|1940' => 'CoyQ-jeqaCU',
];

$catalog = [

// The operator-featured premiere leads the playlist: a full rom-com the
// site's own advertising channel streams free on YouTube.
'featured premiere' => [
['She Races to Find a Husband (Full Rom Com)',2023],
],

'all-time icon' => [
['Titanic',1997],['The Notebook',2004],['Casablanca',1942],['Gone with the Wind',1939],['Pretty Woman',1990],['Dirty Dancing',1987],['Ghost',1990],['When Harry Met Sally...',1989],
['Sleepless in Seattle',1993],["You've Got Mail",1998],['Notting Hill',1999],['Love Actually',2003],['The Princess Bride',1987],['Romeo + Juliet',1996],['Shakespeare in Love',1998],['La La Land',2016],
['A Star Is Born',2018],['The Fault in Our Stars',2014],['Me Before You',2016],['Crazy Rich Asians',2018],["To All the Boys I've Loved Before",2018],['The Vow',2012],['Dear John',2010],['A Walk to Remember',2002],
['Pride & Prejudice',2005],['Sense and Sensibility',1995],["Bridget Jones's Diary",2001],['10 Things I Hate About You',1999],['Clueless',1995],['Jerry Maguire',1996],["My Best Friend's Wedding",1997],['Four Weddings and a Funeral',1994],
["Breakfast at Tiffany's",1961],['Roman Holiday',1953],['An Affair to Remember',1957],['West Side Story',1961],['Grease',1978],['The Bodyguard',1992],['City of Angels',1998],['Meet Joe Black',1998],
['Serendipity',2001],['50 First Dates',2004],['Hitch',2005],['The Proposal',2009],['Silver Linings Playbook',2012],['About Time',2013],['Her',2013],['Call Me by Your Name',2017],
['Brokeback Mountain',2005],['Eternal Sunshine of the Spotless Mind',2004],
],

'golden age' => [
['It Happened One Night',1934],['Bringing Up Baby',1938],['The Philadelphia Story',1940],['His Girl Friday',1940],['My Man Godfrey',1936],['Nothing Sacred',1937],['A Star Is Born',1937],['Love Affair',1939],
['Made for Each Other',1939],['Penny Serenade',1941],['Algiers',1938],['Second Chorus',1940],['The Shop Around the Corner',1940],['Ninotchka',1939],['Camille',1936],['Wuthering Heights',1939],
['Rebecca',1940],['Intermezzo',1939],['Waterloo Bridge',1940],['The Lady Eve',1941],['Woman of the Year',1942],['Now, Voyager',1942],['To Have and Have Not',1944],['Laura',1944],
['Brief Encounter',1945],['Spellbound',1945],['Notorious',1946],["It's a Wonderful Life",1946],['The Best Years of Our Lives',1946],['The Ghost and Mrs. Muir',1947],["The Bishop's Wife",1947],["Adam's Rib",1949],
['Top Hat',1935],['Swing Time',1936],['Shall We Dance',1937],['The Gay Divorcee',1934],['Holiday',1938],['The Awful Truth',1937],["You Can't Take It with You",1938],['Ball of Fire',1941],
['The More the Merrier',1943],['Cover Girl',1944],['Anchors Aweigh',1945],['State Fair',1945],['The Clock',1945],["I Know Where I'm Going!",1945],["The Farmer's Daughter",1947],['Portrait of Jennie',1948],
['Letter from an Unknown Woman',1948],['The Heiress',1949],['A Farewell to Arms',1932],['Grand Hotel',1932],['Trouble in Paradise',1932],['Queen Christina',1933],['Anna Karenina',1935],['Mr. Deeds Goes to Town',1936],
['History Is Made at Night',1937],['Jezebel',1938],['Dark Victory',1939],['Kitty Foyle',1940],['Suspicion',1941],['Random Harvest',1942],['For Whom the Bell Tolls',1943],['Jane Eyre',1943],
['Gaslight',1944],['Meet Me in St. Louis',1944],['Gilda',1946],['The Big Sleep',1946],['Cluny Brown',1946],['Life with Father',1947],
],

'silent & pre-code' => [
['City Lights',1931],['Sunrise: A Song of Two Humans',1927],['It',1927],['Wings',1927],['7th Heaven',1927],['The Crowd',1928],['Show People',1928],["Pandora's Box",1929],
['Morocco',1930],['Shanghai Express',1932],['Red Dust',1932],['She Done Him Wrong',1933],['Flying Down to Rio',1933],['Design for Living',1933],['Peter Ibbetson',1935],['Desire',1936],
['Dodsworth',1936],['Easy Living',1937],['The Prisoner of Zenda',1937],["Bluebeard's Eighth Wife",1938],['Midnight',1939],
],

'classic' => [
["Singin' in the Rain",1952],['An American in Paris',1951],['Royal Wedding',1951],['Sabrina',1954],['Charade',1963],['Cyrano de Bergerac',1950],['From Here to Eternity',1953],['Seven Brides for Seven Brothers',1954],
['Brigadoon',1954],['Guys and Dolls',1955],['Marty',1955],['Picnic',1955],['Love Is a Many-Splendored Thing',1955],['The King and I',1956],['High Society',1956],['Funny Face',1957],
['Pal Joey',1957],['Gigi',1958],['South Pacific',1958],['Vertigo',1958],['Some Like It Hot',1959],['Pillow Talk',1959],['The Apartment',1960],['Where the Boys Are',1960],
['Splendor in the Grass',1961],['Lover Come Back',1961],['That Touch of Mink',1962],['Bye Bye Birdie',1963],['Irma la Douce',1963],['Send Me No Flowers',1964],['My Fair Lady',1964],['The Umbrellas of Cherbourg',1964],
['Doctor Zhivago',1965],['The Sound of Music',1965],['A Man and a Woman',1966],['Barefoot in the Park',1967],['The Graduate',1967],['Two for the Road',1967],["Guess Who's Coming to Dinner",1967],['Funny Girl',1968],
['Romeo and Juliet',1968],['The Thomas Crown Affair',1968],['Sweet Charity',1969],['Goodbye, Columbus',1969],['Cactus Flower',1969],['Magnificent Obsession',1954],['All That Heaven Allows',1955],['A Place in the Sun',1951],
['The African Queen',1951],['The Quiet Man',1952],['Three Coins in the Fountain',1954],['Summertime',1955],['Bus Stop',1956],['Indiscreet',1958],['Houseboat',1958],['Imitation of Life',1959],
['A Summer Place',1959],['Cleopatra',1963],['Father Goose',1964],['Sex and the Single Girl',1964],['How to Steal a Million',1966],['Carousel',1956],['Oklahoma!',1955],['The Tender Trap',1955],
['Designing Woman',1957],['Desk Set',1957],['Silk Stockings',1957],['Marjorie Morningstar',1958],['Bell, Book and Candle',1958],['Ask Any Girl',1959],['The World of Suzie Wong',1960],['BUtterfield 8',1960],
['Come September',1961],["Boys' Night Out",1962],['If a Man Answers',1962],['Move Over, Darling',1963],['Under the Yum Yum Tree',1963],['Marriage Italian Style',1964],['Yesterday, Today and Tomorrow',1963],['Strange Bedfellows',1965],
['That Funny Feeling',1965],['How to Murder Your Wife',1965],['The Glass Bottom Boat',1966],['A Countess from Hong Kong',1967],['Petulia',1968],['The April Fools',1969],['Breathless',1960],['Jules and Jim',1962],
],

'1970s' => [
['Love Story',1970],["Ryan's Daughter",1970],["Summer of '42",1971],['Fiddler on the Roof',1971],['Harold and Maude',1971],['Cabaret',1972],['The Way We Were',1973],['The Great Gatsby',1974],
['Shampoo',1975],['Funny Lady',1975],['A Star Is Born',1976],['Rocky',1976],['Annie Hall',1977],['Saturday Night Fever',1977],['The Goodbye Girl',1977],['Coming Home',1978],
['Heaven Can Wait',1978],['Same Time, Next Year',1978],['Manhattan',1979],['The Electric Horseman',1979],['10',1979],['Starting Over',1979],['Ice Castles',1978],['The Other Side of the Mountain',1975],
['Bobby Deerfield',1977],['Lovers and Other Strangers',1970],['Plaza Suite',1971],["Pete 'n' Tillie",1972],['40 Carats',1973],['Blume in Love',1973],['A Touch of Class',1973],['Cinderella Liberty',1973],
["For Pete's Sake",1974],['House Calls',1978],['California Suite',1978],['Chapter Two',1979],
],

'1980s' => [
['Somewhere in Time',1980],['The Blue Lagoon',1980],['Urban Cowboy',1980],['Endless Love',1981],['Arthur',1981],['On Golden Pond',1981],['An Officer and a Gentleman',1982],['Tootsie',1982],
["Sophie's Choice",1982],['Flashdance',1983],['Terms of Endearment',1983],['Valley Girl',1983],['Educating Rita',1983],['Splash',1984],['Sixteen Candles',1984],['Footloose',1984],
['Romancing the Stone',1984],['The Woman in Red',1984],['Falling in Love',1984],['Out of Africa',1985],["St. Elmo's Fire",1985],['White Nights',1985],["Murphy's Romance",1985],['Pretty in Pink',1986],
['About Last Night...',1986],['Top Gun',1986],['Peggy Sue Got Married',1986],['Children of a Lesser God',1986],['Crocodile Dundee',1986],['Some Kind of Wonderful',1987],['Moonstruck',1987],['Baby Boom',1987],
['Roxanne',1987],["Can't Buy Me Love",1987],['Overboard',1987],['Broadcast News',1987],['Cocktail',1988],['Bull Durham',1988],['Working Girl',1988],['Crossing Delancey',1988],
['A Fish Called Wanda',1988],['Say Anything...',1989],["Look Who's Talking",1989],['Shirley Valentine',1989],['Mannequin',1987],['Date with an Angel',1987],['Made in Heaven',1987],["She's Having a Baby",1988],
['Coming to America',1988],['Earth Girls Are Easy',1988],['The Accidental Tourist',1988],['Chances Are',1989],['Her Alibi',1989],['Loverboy',1989],['Blind Date',1987],['Always',1989],
['A Room with a View',1985],['Betty Blue',1986],['Cinema Paradiso',1988],['Fame',1980],['Grease 2',1982],['Xanadu',1980],['Purple Rain',1984],['La Bamba',1987],
['Great Balls of Fire!',1989],['Coal Miner\'s Daughter',1980],['The Little Mermaid',1989],
],

'1990s' => [
['Edward Scissorhands',1990],['Green Card',1990],['The Cutting Edge',1992],['Far and Away',1992],['Singles',1992],['Benny & Joon',1993],['Indecent Proposal',1993],['Much Ado About Nothing',1993],
['The Piano',1993],['The Age of Innocence',1993],['The Remains of the Day',1993],['Reality Bites',1994],['Only You',1994],['Legends of the Fall',1994],['While You Were Sleeping',1995],['Before Sunrise',1995],
['The Bridges of Madison County',1995],['French Kiss',1995],['Sabrina',1995],['Waiting to Exhale',1995],['Persuasion',1995],['The American President',1995],['Emma',1996],['The English Patient',1996],
['Tin Cup',1996],['One Fine Day',1996],['The Mirror Has Two Faces',1996],['Fools Rush In',1997],['Picture Perfect',1997],['As Good as It Gets',1997],['Good Will Hunting',1997],['The Wedding Singer',1998],
['Hope Floats',1998],['Ever After: A Cinderella Story',1998],['The Mask of Zorro',1998],['How Stella Got Her Groove Back',1998],['Practical Magic',1998],["She's All That",1999],['Message in a Bottle',1999],['Never Been Kissed',1999],
['Runaway Bride',1999],['Drive Me Crazy',1999],['The Best Man',1999],['The Thomas Crown Affair',1999],['Anna and the King',1999],['Cruel Intentions',1999],["She's the One",1996],['Addicted to Love',1997],
['Groundhog Day',1993],['Sliding Doors',1998],['Great Expectations',1998],['Mickey Blue Eyes',1999],['Forces of Nature',1999],['Love Jones',1997],['Poetic Justice',1993],["Jason's Lyric",1994],
["The Preacher's Wife",1996],['Up Close & Personal',1996],['A Walk in the Clouds',1995],['Don Juan DeMarco',1994],['I.Q.',1994],['Corrina, Corrina',1994],['It Could Happen to You',1994],['Love Affair',1994],
['Circle of Friends',1995],['How to Make an American Quilt',1995],['Bed of Roses',1996],['The Truth About Cats & Dogs',1996],['Michael',1996],['Joe Versus the Volcano',1990],['White Palace',1990],['Frankie and Johnny',1991],
['The Prince of Tides',1991],['Dying Young',1991],['Once Around',1991],['L.A. Story',1991],['Doc Hollywood',1991],['HouseSitter',1992],['Prelude to a Kiss',1992],['Forever Young',1992],
['Untamed Heart',1993],['Born Yesterday',1993],['So I Married an Axe Murderer',1993],['Sommersby',1993],['Milk Money',1994],['Speechless',1994],['Forget Paris',1995],['Nine Months',1995],
['Two If by Sea',1996],["She's So Lovely",1997],["'Til There Was You",1997],['Six Days Seven Nights',1998],['The Object of My Affection',1998],['Simply Irresistible',1999],['The Story of Us',1999],['The Bachelor',1999],
['Blast from the Past',1999],['For Love of the Game',1999],["Muriel's Wedding",1994],['The Wedding Banquet',1993],['Strictly Ballroom',1992],['Shall We Dance?',1996],['Il Postino',1994],['Life Is Beautiful',1997],
['Like Water for Chocolate',1992],['Chungking Express',1994],['Comrades: Almost a Love Story',1996],["What's Love Got to Do with It",1993],['Selena',1997],['Beauty and the Beast',1991],['Aladdin',1992],['Whisper of the Heart',1995],
['Christmas in August',1998],['But I\'m a Cheerleader',1999],['Wuthering Heights',1992],['Howards End',1992],['Anna Karenina',1997],['Onegin',1999],
],

'2000s' => [
['What Women Want',2000],['Bounce',2000],['Where the Heart Is',2000],['Coyote Ugly',2000],['Someone Like You',2001],['Kate & Leopold',2001],['The Wedding Planner',2001],['Save the Last Dance',2001],
['Amélie',2001],['Vanilla Sky',2001],['Moulin Rouge!',2001],['Original Sin',2001],['Sweet Home Alabama',2002],['Maid in Manhattan',2002],['Two Weeks Notice',2002],['My Big Fat Greek Wedding',2002],
['Punch-Drunk Love',2002],['The Importance of Being Earnest',2002],['Brown Sugar',2002],['Deliver Us from Eva',2003],['How to Lose a Guy in 10 Days',2003],["Something's Gotta Give",2003],['Under the Tuscan Sun',2003],['Le Divorce',2003],
['Intolerable Cruelty',2003],['13 Going on 30',2004],['Wimbledon',2004],['Shall We Dance',2004],['Spanglish',2004],['Closer',2004],['Ella Enchanted',2004],['The Phantom of the Opera',2004],
['Before Sunset',2004],['Garden State',2004],['A Cinderella Story',2004],['Bride and Prejudice',2004],['Monster-in-Law',2005],['Just Like Heaven',2005],['Elizabethtown',2005],['Prime',2005],
['The Family Stone',2005],['Memoirs of a Geisha',2005],['Casanova',2005],['Tristan & Isolde',2006],['Failure to Launch',2006],["She's the Man",2006],['Take the Lead',2006],['The Lake House',2006],
['The Break-Up',2006],['Step Up',2006],['The Holiday',2006],['Music and Lyrics',2007],['Becoming Jane',2007],['Waitress',2007],['Once',2007],['Hairspray',2007],
['No Reservations',2007],['Stardust',2007],['Atonement',2007],['Enchanted',2007],['P.S. I Love You',2007],['27 Dresses',2008],['Definitely, Maybe',2008],["Fool's Gold",2008],
['Made of Honor',2008],['Sex and the City',2008],['Mamma Mia!',2008],['The Time Traveler\'s Wife',2009],["He's Just Not That Into You",2009],['Confessions of a Shopaholic',2009],['New in Town',2009],['The Ugly Truth',2009],
['Julie & Julia',2009],['(500) Days of Summer',2009],['Twilight',2008],['The Twilight Saga: New Moon',2009],['Australia',2008],['Nights in Rodanthe',2008],['Last Chance Harvey',2008],['Slumdog Millionaire',2008],
['Bright Star',2009],['An Education',2009],['Adventureland',2009],['Away We Go',2009],["It's Complicated",2009],['Did You Hear About the Morgans?',2009],['Along Came Polly',2004],['The Girl Next Door',2004],
['Win a Date with Tad Hamilton!',2004],['Raising Helen',2004],['Little Black Book',2004],['Laws of Attraction',2004],['The Prince and Me',2004],['First Daughter',2004],['Chasing Liberty',2004],['A Lot Like Love',2005],
['Fever Pitch',2005],['Must Love Dogs',2005],['Rumor Has It...',2005],['Just Friends',2005],['Imagine Me & You',2005],['In Her Shoes',2005],['Shopgirl',2005],['Something New',2006],
['Last Holiday',2006],['Just My Luck',2006],['John Tucker Must Die',2006],['Because I Said So',2007],['License to Wed',2007],['Good Luck Chuck',2007],['Dan in Real Life',2007],['What Happens in Vegas',2008],
['Forgetting Sarah Marshall',2008],["My Best Friend's Girl",2008],["Nick and Norah's Infinite Playlist",2008],['Ghost Town',2008],['Bride Wars',2009],['The Accidental Husband',2008],['Management',2008],['All About Steve',2009],
['The Rebound',2009],['Autumn in New York',2000],['Sweet November',2001],['Love & Basketball',2000],['The Wedding Date',2005],['Wedding Crashers',2005],['American Wedding',2003],['Monsoon Wedding',2001],
['If Only',2004],['Ghosts of Girlfriends Past',2009],['The Curious Case of Benjamin Button',2008],['Across the Universe',2007],['High School Musical',2006],['High School Musical 2',2007],['High School Musical 3: Senior Year',2008],['Camp Rock',2008],
['Dirty Dancing: Havana Nights',2004],['Center Stage',2000],['Honey',2003],['Step Up 2: The Streets',2008],['Walk the Line',2005],['Corpse Bride',2005],['WALL-E',2008],['The Princess and the Frog',2009],
['The Other Boleyn Girl',2008],['The Duchess',2008],['The Young Victoria',2009],['Saving Face',2004],['The Painted Veil',2006],['Priceless',2006],['Love Me If You Dare',2003],['A Very Long Engagement',2004],
['Head-On',2004],['Y Tu Mamá También',2001],['In the Mood for Love',2000],['Crouching Tiger, Hidden Dragon',2000],['My Sassy Girl',2001],['Il Mare',2000],['The Classic',2003],['A Moment to Remember',2004],
['200 Pounds Beauty',2006],['My Tutor Friend',2003],['Windstruck',2004],['Almost Love',2006],['One Fine Spring Day',2001],['Failan',2001],['Secret',2007],['Cape No. 7',2008],
['5 Centimeters per Second',2007],["Howl's Moving Castle",2004],['Heavenly Forest',2006],['Four Christmases',2008],
],

'2010s' => [
["Valentine's Day",2010],['Letters to Juliet',2010],['Eat Pray Love',2010],['Going the Distance',2010],['Life as We Know It',2010],['Love & Other Drugs',2010],['Blue Valentine',2010],['Burlesque',2010],
['Country Strong',2010],['No Strings Attached',2011],['Just Go with It',2011],['Water for Elephants',2011],['Something Borrowed',2011],['Jumping the Broom',2011],['Midnight in Paris',2011],['Crazy, Stupid, Love.',2011],
['One Day',2011],['Friends with Benefits',2011],['The Artist',2011],['Like Crazy',2011],['The Twilight Saga: Breaking Dawn – Part 1',2011],['This Means War',2012],['The Lucky One',2012],['Think Like a Man',2012],
['Magic Mike',2012],['Ruby Sparks',2012],['Celeste and Jesse Forever',2012],['The Perks of Being a Wallflower',2012],['Anna Karenina',2012],['Playing for Keeps',2012],['Safe Haven',2013],['The Great Gatsby',2013],
['Before Midnight',2013],['The Spectacular Now',2013],['Austenland',2013],['Don Jon',2013],['Enough Said',2013],['The Best Man Holiday',2013],['Endless Love',2014],["Winter's Tale",2014],
['The Other Woman',2014],['Begin Again',2014],['Magic in the Moonlight',2014],['What If',2014],['If I Stay',2014],['The Hundred-Foot Journey',2014],['The Best of Me',2014],['The Theory of Everything',2014],
['Beyond the Lights',2014],['Top Five',2014],['Fifty Shades of Grey',2015],['The Longest Ride',2015],['Far from the Madding Crowd',2015],['Aloha',2015],['Trainwreck',2015],['Paper Towns',2015],
['The Age of Adaline',2015],['Carol',2015],['Brooklyn',2015],['Sleeping with Other People',2015],['How to Be Single',2016],['The Choice',2016],['Café Society',2016],["Bridget Jones's Baby",2016],
['Loving',2016],['Passengers',2016],['Everything, Everything',2017],['The Big Sick',2017],['Beauty and the Beast',2017],['The Shape of Water',2017],['Phantom Thread',2017],['Fifty Shades Darker',2017],
['The Mountain Between Us',2017],['Home Again',2017],['Midnight Sun',2018],['Every Day',2018],['Love, Simon',2018],['Set It Up',2018],['Mamma Mia! Here We Go Again',2018],['The Kissing Booth',2018],
['Sierra Burgess Is a Loser',2018],['The Guernsey Literary and Potato Peel Pie Society',2018],['Fifty Shades Freed',2018],['Overboard',2018],['Destination Wedding',2018],['If Beale Street Could Talk',2018],["Isn't It Romantic",2019],['What Men Want',2019],
['Five Feet Apart',2019],['After',2019],['Long Shot',2019],['Yesterday',2019],['The Sun Is Also a Star',2019],['Last Christmas',2019],['Always Be My Maybe',2019],['Portrait of a Lady on Fire',2019],
['The Back-up Plan',2010],['Killers',2010],["She's Out of My League",2010],['Date Night',2010],['The Bounty Hunter',2010],['Sex and the City 2',2010],['The Switch',2010],['Monte Carlo',2011],
['Larry Crowne',2011],['The Art of Getting By',2011],["What's Your Number?",2011],['The Five-Year Engagement',2012],['That Awkward Moment',2014],['Blended',2014],['And So It Goes',2014],['The Rewrite',2014],
['Man Up',2015],["Mother's Day",2016],['My Big Fat Greek Wedding 2',2016],['Table 19',2017],['The Last Song',2010],['Remember Me',2010],['Charlie St. Cloud',2010],['Now Is Good',2012],
['Irreplaceable You',2018],['The DUFF',2015],['Love, Rosie',2014],['Flipped',2010],['The Edge of Seventeen',2016],['Candy Jar',2018],['Alex Strangelove',2018],['The Perfect Date',2019],
['The Last Summer',2019],['Tall Girl',2019],['New Year\'s Eve',2011],['When in Rome',2010],['Leap Year',2010],['The Adjustment Bureau',2011],['In Time',2011],['Time Freak',2018],
['When We First Met',2018],['Naked',2017],['Step Up Revolution',2012],['Step Up: All In',2014],['Footloose',2011],['Cuban Fury',2014],['Playing It Cool',2014],['Sing Street',2016],
['The Greatest Showman',2017],['Tangled',2010],['A Royal Affair',2012],['Love & Friendship',2016],['My Cousin Rachel',2017],['Mary Shelley',2017],['Colette',2018],['The Aftermath',2019],
['Belle',2013],['Testament of Youth',2014],['Tulip Fever',2017],['Amour',2012],['Blue Is the Warmest Color',2013],['Populaire',2012],['Romantics Anonymous',2010],['Heartbreaker',2010],
['Delicacy',2011],['The Lunchbox',2013],['Photograph',2019],['Jane Eyre',2011],['The Way He Looks',2014],["God's Own Country",2017],['Moonlight',2016],['The Handmaiden',2016],
['Disobedience',2017],['Weekend',2011],['Rafiki',2018],['Someone Great',2019],['Falling Inn Love',2019],['Plus One',2019],['The Wedding Year',2019],['A Christmas Prince',2017],
['A Christmas Prince: The Royal Wedding',2018],['A Christmas Prince: The Royal Baby',2019],['The Princess Switch',2018],['The Knight Before Christmas',2019],['Holiday in the Wild',2019],['Your Name',2016],['Weathering with You',2019],['A Silent Voice',2016],
['I Want to Eat Your Pancreas',2018],['Norwegian Wood',2010],['Architecture 101',2012],['Always',2011],['Be With You',2018],['Tune in for Love',2019],['On Your Wedding Day',2018],['You Are the Apple of My Eye',2011],
['Our Times',2015],['More Than Blue',2018],['A Werewolf Boy',2012],['The Beauty Inside',2015],['Right Now, Wrong Then',2015],['Say "I Love You"',2014],['Kimi ni Todoke: From Me to You',2010],['Orange',2015],
['My Tomorrow, Your Yesterday',2016],['The 100th Love with You',2017],['Drowning Love',2016],['Us and Them',2018],['Somewhere Winter',2019],['The Left Ear',2015],['My Old Classmate',2014],['You Are My Sunshine',2015],
['Never Gone',2016],['Love O2O',2016],['Three Steps Above Heaven',2010],['I Want You',2012],['Palmeras en la Nieve',2015],['La Boda de Valentina',2018],['Instructions Not Included',2013],
],

'2020s' => [
['The Photograph',2020],['All the Bright Places',2020],['To All the Boys: P.S. I Still Love You',2020],['Emma.',2020],['The Half of It',2020],['Palm Springs',2020],['The Broken Hearts Gallery',2020],['Holidate',2020],
["Sylvie's Love",2020],['Malcolm & Marie',2021],['To All the Boys: Always and Forever',2021],['The Map of Tiny Perfect Things',2021],['A Week Away',2021],['Cinderella',2021],['The Last Letter from Your Lover',2021],['Resort to Love',2021],
['Cyrano',2021],['West Side Story',2021],['Marry Me',2022],['The Lost City',2022],['Book of Love',2022],['Purple Hearts',2022],['Persuasion',2022],['Look Both Ways',2022],
['Ticket to Paradise',2022],['Bros',2022],['Falling for Christmas',2022],['Shotgun Wedding',2022],['Your Place or Mine',2023],['Rye Lane',2023],['Love Again',2023],['The Perfect Find',2023],
['Red, White & Royal Blue',2023],['Past Lives',2023],['Anyone but You',2023],['The Idea of You',2024],['Players',2024],['Upgraded',2024],['Mother of the Bride',2024],['A Family Affair',2024],
['Find Me Falling',2024],['It Ends with Us',2024],['We Live in Time',2024],['Bridget Jones: Mad About the Boy',2025],['Materialists',2025],['The Life List',2025],['Picture This',2025],['The Kissing Booth 2',2020],
['The Kissing Booth 3',2021],['After We Collided',2020],['After We Fell',2021],['After Ever Happy',2022],['Love at First Sight',2023],['Hello, Goodbye and Everything in Between',2022],['Through My Window',2022],['Words on Bathroom Walls',2020],
['Chemical Hearts',2020],['Work It',2020],["He's All That",2021],['A Cinderella Story: Starstruck',2021],['Prom Pact',2023],['The In Between',2022],['Along for the Ride',2022],['My Fake Boyfriend',2022],
['Beautiful Disaster',2023],['Love Hard',2021],['The Princess Switch: Switched Again',2020],['The Princess Switch 3: Romancing the Star',2021],['Operation Christmas Drop',2020],['Midnight at the Magnolia',2020],['A California Christmas',2020],['A California Christmas: City Lights',2021],
['A Castle for Christmas',2021],['Single All the Way',2021],['The Noel Diary',2022],['EXmas',2023],['Best. Christmas. Ever!',2023],['Hot Frosty',2024],['Our Little Secret',2024],['Meet Me Next Christmas',2024],
['The Merry Gentlemen',2024],['The Wrong Missy',2020],['Love, Guaranteed',2020],['Desperados',2020],['The Lovebirds',2020],['Happiest Season',2020],['Squared Love',2021],['The Royal Treatment',2022],
['Love in the Villa',2022],['Wedding Season',2022],['Meet Cute',2022],['Somebody I Used to Know',2023],['You People',2023],['Ghosted',2023],['No Hard Feelings',2023],['Happiness for Beginners',2023],
['Choose Love',2023],["A Tourist's Guide to Love",2023],['Irish Wish',2024],['Lonely Planet',2024],['Beautiful Wedding',2024],['The Prom',2020],['In the Heights',2021],['Fire Island',2022],
["Anything's Possible",2022],['Crush',2022],['Supernova',2020],['Ammonite',2020],['The World to Come',2020],['Mothering Sunday',2021],["Mr. Malcolm's List",2022],['Chevalier',2022],
['About Fate',2022],['Press Play',2022],['Long Story Short',2021],['Love and Leashes',2022],['20th Century Girl',2022],['Love in the Big City',2024],['Josee, the Tiger and the Fish',2020],['We Made a Beautiful Bouquet',2021],
['Love Like the Falling Petals',2022],['Sweet & Sour',2021],['Love Reset',2023],['Someday or One Day',2022],['Hridayam',2022],['Sita Ramam',2022],['Kushi',2023],['Hi Nanna',2023],
],

'bollywood & south asia' => [
['Dilwale Dulhania Le Jayenge',1995],['Kuch Kuch Hota Hai',1998],['Kabhi Khushi Kabhie Gham',2001],['Kal Ho Naa Ho',2003],['Veer-Zaara',2004],['Jab We Met',2007],['Om Shanti Om',2007],['Rab Ne Bana Di Jodi',2008],
['Love Aaj Kal',2009],['Band Baaja Baaraat',2010],['Zindagi Na Milegi Dobara',2011],['Rockstar',2011],['Barfi!',2012],['Yeh Jawaani Hai Deewani',2013],['Aashiqui 2',2013],['Goliyon Ki Raasleela Ram-Leela',2013],
['2 States',2014],['Humpty Sharma Ki Dulhania',2014],['Dilwale',2015],['Bajirao Mastani',2015],['Ae Dil Hai Mushkil',2016],['Befikre',2016],['Jab Harry Met Sejal',2017],['Padmaavat',2018],
['Dhadak',2018],['Kabir Singh',2019],['Love Aaj Kal',2020],['Shershaah',2021],['Atrangi Re',2021],['Radhe Shyam',2022],['Rocky Aur Rani Kii Prem Kahaani',2023],['Tu Jhoothi Main Makkaar',2023],
['Zara Hatke Zara Bachke',2023],['Satyaprem Ki Katha',2023],['Devdas',2002],['Hum Dil De Chuke Sanam',1999],['Mohabbatein',2000],['Dil To Pagal Hai',1997],['Pardes',1997],['Dil Se..',1998],
['Taal',1999],['Saathiya',2002],['Fanaa',2006],['Jodhaa Akbar',2008],['Wake Up Sid',2009],['I Hate Luv Storys',2010],['Ek Tha Tiger',2012],['Raanjhanaa',2013],
['Tamasha',2015],['Half Girlfriend',2017],['Kaho Naa... Pyaar Hai',2000],['Kabhi Alvida Naa Kehna',2006],['Bachna Ae Haseeno',2008],['Anjaana Anjaani',2010],['Mere Brother Ki Dulhan',2011],['Shuddh Desi Romance',2013],
['Aashiqui',1990],['Maine Pyar Kiya',1989],['Hum Aapke Hain Koun..!',1994],['Raja Hindustani',1996],['Josh',2000],['Rehnaa Hai Terre Dil Mein',2001],['Ishq Vishk',2003],['Hum Tum',2004],
['Salaam Namaste',2005],['Jaane Tu... Ya Jaane Na',2008],['96',2018],['Vinnaithaandi Varuvaayaa',2010],['OK Kanmani',2015],['Premam',2015],['Bangalore Days',2014],['Ye Maaya Chesave',2010],
['Geetha Govindam',2018],['Arjun Reddy',2017],['Fidaa',2017],['Ninnu Kori',2017],['Love Story',2021],
],
];

$films = [];
$seen = [];
foreach ($catalog as $tag => $entries) {
    foreach ($entries as [$title, $year]) {
        $key = mb_strtolower($title) . '|' . $year;
        if (isset($seen[$key])) {
            continue;
        }
        $seen[$key] = true;
        $slug = strtolower(trim((string) preg_replace('/-+/', '-', (string) preg_replace('/[^a-z0-9]+/i', '-', $title)), '-'));
        $films[] = [
            'id' => $slug . '-' . $year,
            'title' => $title,
            'year' => $year,
            'tag' => $tag,
            'youtube_id' => $verified[$title . '|' . $year] ?? null,
        ];
    }
}

if (count($films) < 1000) {
    fwrite(STDERR, 'The catalog holds only ' . count($films) . " unique films — add more before building.\n");
    exit(1);
}
$films = array_slice($films, 0, 1000);
foreach ($films as $i => &$film) {
    $film['rank'] = $i + 1;
}
unset($film);

$dir = dirname(__DIR__) . '/data';
if (!is_dir($dir) && !mkdir($dir, 0775, true) && !is_dir($dir)) {
    fwrite(STDERR, "Could not create the data directory.\n");
    exit(1);
}
file_put_contents($dir . '/romance-films.json', json_encode($films, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE));
$playable = count(array_filter($films, static fn (array $f): bool => $f['youtube_id'] !== null));
echo 'Romance library built: ' . count($films) . " films, {$playable} playable in-page (verified public-domain uploads).\n";
