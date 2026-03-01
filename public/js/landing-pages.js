/* =====================================================
   SmileLoop – Landing Page Variants
   Dynamic content driven by URL slug.
   Add new categories here — zero code changes elsewhere.
   ===================================================== */

// eslint-disable-next-line no-unused-vars
var LANDING_PAGES = {

  /* ─────────────────────────────────────────────────── */
  /*  DEFAULT  (homepage / unknown slug)                 */
  /* ─────────────────────────────────────────────────── */
  _default: {
    slug: '',
    pageTitle: 'SmileLoop – Bring Your Photo to Life',
    metaDescription: 'Upload a photo. Watch it smile. Turn your still photos into gentle, living memories.',
    headline: 'Bring Your Photo to Life.',
    subheadline: 'Upload a photo. Watch it smile.',
    testimonial: {
      quote: '"I showed my mom and she cried happy tears."',
      author: 'Sarah K.',
    },
    emotionalText: 'Sometimes all it takes is a blink.<br>A smile.<br>A small movement.<br><br>And it feels warm again.',
    demoBefore: '/assets/demo-before.jpg',
    demoAfter: '/assets/demo-after.mp4',
    trustBadges: ['🔒 100% Private & Deleted', '⚡ Ready in ~30 sec', '💳 No subscription'],
    socialProof: { rating: '4.9/5', stars: '★★★★★' },
  },

  /* ─────────────────────────────────────────────────── */
  /*  🍼 BABY / NEWBORN                                 */
  /* ─────────────────────────────────────────────────── */
  'baby-photos': {
    slug: 'baby-photos',
    pageTitle: 'SmileLoop – Bring Your Baby Photo to Life',
    metaDescription: 'Turn a baby photo into a living memory. Watch that first smile come to life.',
    headline: 'Bring Your Baby\u2019s Photo to Life.',
    subheadline: 'See that first smile again. Turn a baby photo into a living memory.',
    testimonial: {
      quote: '"I turned my newborn\'s hospital photo into a gentle smile. I can\'t stop watching it."',
      author: 'Emily R., new mom',
    },
    emotionalText: 'That tiny yawn.<br>Those little eyes opening.<br>A first smile you almost missed.<br><br>Now it\'s alive again.',
    demoBefore: '/assets/demo-before.jpg',
    demoAfter: '/assets/demo-after.mp4',
    trustBadges: ['🔒 100% Private & Deleted', '⚡ Ready in ~30 sec', '💳 No subscription'],
    socialProof: { rating: '4.9/5', stars: '★★★★★' },
  },

  /* ─────────────────────────────────────────────────── */
  /*  👨‍👩‍👧 FAMILY MOMENTS                               */
  /* ─────────────────────────────────────────────────── */
  'family-photos': {
    slug: 'family-photos',
    pageTitle: 'SmileLoop – Make a Family Photo Smile',
    metaDescription: 'Bring your favorite family memory back to life. That one photo — now alive.',
    headline: 'Make a Family Photo Smile.',
    subheadline: 'Bring your favorite memory back to life. That one photo — now alive.',
    testimonial: {
      quote: '"We turned our holiday family photo into a little video. Everyone in the group chat went crazy."',
      author: 'David L.',
    },
    emotionalText: 'A holiday dinner.<br>A backyard afternoon.<br>Everyone together, just for a moment.<br><br>Now it moves again.',
    demoBefore: '/assets/demo-before.jpg',
    demoAfter: '/assets/demo-after.mp4',
    trustBadges: ['🔒 100% Private & Deleted', '⚡ Ready in ~30 sec', '🎁 Perfect gift'],
    socialProof: { rating: '4.9/5', stars: '★★★★★' },
  },

  /* ─────────────────────────────────────────────────── */
  /*  👴 OLD PHOTO / GRANDPARENTS / NOSTALGIA           */
  /* ─────────────────────────────────────────────────── */
  'vintage-portraits': {
    slug: 'vintage-portraits',
    pageTitle: 'SmileLoop – See Grandma Smile Again',
    metaDescription: 'Restore and bring an old photo to life. See loved ones smile again with a gentle animation.',
    headline: 'See Grandma Smile Again.',
    subheadline: 'Restore and bring an old photo to life. A classic portrait, gently alive.',
    testimonial: {
      quote: '"I uploaded my grandfather\'s portrait from the 1960s. When he smiled, I felt like he was right here."',
      author: 'Maria T.',
    },
    emotionalText: 'A faded portrait.<br>A face you haven\'t seen in years.<br>A smile you almost forgot.<br><br>Now it\'s back.',
    demoBefore: '/assets/demo-before.jpg',
    demoAfter: '/assets/demo-after.mp4',
    trustBadges: ['🔒 100% Private & Deleted', '⚡ Ready in ~30 sec', '🖼️ Works with old photos'],
    socialProof: { rating: '4.9/5', stars: '★★★★★' },
  },

  /* ─────────────────────────────────────────────────── */
  /*  💑 COUPLES / ROMANTIC                             */
  /* ─────────────────────────────────────────────────── */
  'couple-photos': {
    slug: 'couple-photos',
    pageTitle: 'SmileLoop – Turn Your Favorite Photo Into a Smile',
    metaDescription: 'Relive that moment. Turn your favorite couple photo into a gentle, living memory.',
    headline: 'Turn Your Favorite Photo Into a Smile.',
    subheadline: 'Relive that moment. Your photo — gently alive.',
    testimonial: {
      quote: '"I animated our wedding photo for our anniversary. My wife teared up. Best surprise ever."',
      author: 'James & Sofia',
    },
    emotionalText: 'A first date.<br>A wedding day.<br>A quiet moment together.<br><br>Now it breathes again.',
    demoBefore: '/assets/demo-before.jpg',
    demoAfter: '/assets/demo-after.mp4',
    trustBadges: ['🔒 100% Private & Deleted', '⚡ Ready in ~30 sec', '💝 Perfect for anniversaries'],
    socialProof: { rating: '4.9/5', stars: '★★★★★' },
  },

  /* ─────────────────────────────────────────────────── */
  /*  😄 GENERAL FUN (broad audience)                   */
  /* ─────────────────────────────────────────────────── */
  'animate-photo': {
    slug: 'animate-photo',
    pageTitle: 'SmileLoop – Upload a Photo, Watch It Smile',
    metaDescription: 'Upload any photo and watch it come alive. Fun, fast, and surprisingly cool.',
    headline: 'Upload a Photo. Watch It Smile.',
    subheadline: 'Your picture — but alive. Try it, it\'s fun.',
    testimonial: {
      quote: '"I tried it with my cat. Then my yearbook photo. Then my boss. I can\'t stop."',
      author: 'Alex P.',
    },
    emotionalText: 'A selfie.<br>A meme.<br>An old yearbook photo.<br><br>Just upload it. You\'ll see.',
    demoBefore: '/assets/demo-before.jpg',
    demoAfter: '/assets/demo-after.mp4',
    trustBadges: ['🔒 100% Private & Deleted', '⚡ Ready in ~30 sec', '😄 Works with any face'],
    socialProof: { rating: '4.9/5', stars: '★★★★★' },
  },
};
