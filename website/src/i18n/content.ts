import type { Loc } from './ui';

export type Block =
  | { kind: 'heading'; text: Loc; id: string }
  | { kind: 'text'; text: Loc }
  | { kind: 'bullets'; items: Loc[] }
  | { kind: 'entries'; items: { title: Loc; body: Loc; meta?: Loc }[] }
  | { kind: 'steps'; items: { title: Loc; body: Loc }[] }
  | { kind: 'note'; text: Loc }
  | { kind: 'link'; label: Loc; href: string }
  | { kind: 'diagram'; label: Loc }
  | { kind: 'commands' }
  | { kind: 'permissions' }
  | { kind: 'changelog' }
  | { kind: 'faq'; items: { q: Loc; a: Loc }[] }
  | { kind: 'cta' };

export type PageDef = {
  slug: string;
  eyebrow: Loc;
  h1: Loc;
  title: Loc;
  description: Loc;
  blocks: Block[];
};

export const home: PageDef = {
  slug: '',
  eyebrow: {
    ar: 'بوت ديسكورد · سيرفرات المجتمع',
    en: 'DISCORD BOT · COMMUNITY SERVERS',
  },
  h1: {
    ar: 'أرشيفٌ يُبحث فيه، وإشرافٌ لا يُنفَّذ إلا بتأكيد.',
    en: 'A searchable archive. Moderation that never acts unconfirmed.',
  },
  title: {
    ar: 'أنجل — بوت ديسكورد عربي لسيرفرات المجتمع',
    en: 'Angel — an Arabic Discord bot for community servers',
  },
  description: {
    ar: 'يحتفظ أنجل بأرشيف قابل للبحث لما يراه، ويحوّل روابط التواصل الاجتماعي إلى ملفات.',
    en: 'Angel keeps a searchable archive of what it sees and turns social links into files.',
  },
  blocks: [
    { kind: 'heading', id: 'what', text: { ar: 'ما يحتفظ به أنجل', en: 'What Angel keeps' } },
    {
      kind: 'entries',
      items: [
        {
          title: { ar: 'أرشيف قابل للبحث', en: 'A searchable archive' },
          body: {
            ar: 'كل رسالة يراها البوت في قناة يستطيع قراءتها تُفهرس في `SQLite FTS5`. البحث يعيد فقط ما يستطيع السائل قراءته، والرسائل الخاصة خارج أرشيف السيرفر.',
            en: 'Every message the bot sees in a channel it can read is indexed in `SQLite FTS5`. Search returns only what the asker may read, and direct messages stay out of the server archive.',
          },
        },
        {
          title: { ar: 'تأكيد لما يقترحه النموذج', en: 'Confirmation for model-proposed actions' },
          body: {
            ar: 'الأوامر التي تكتبها الإدارة تُنفَّذ مباشرة. أما الإجراء التدميري الذي يقترحه النموذج فيُوضع في طابور، ولا يُنفَّذ حتى يكتب من طلبه «تأكيد» خلال 60 ثانية، مع إعادة مراجعة الصلاحية عند التأكيد.',
            en: 'Commands your staff type run directly. A destructive action the model proposes is queued instead, and does not run until the person who requested it types “confirm” within 60 seconds; the permission is re-checked at that point.',
          },
        },
        {
          title: { ar: 'وسائط من الروابط', en: 'Media from links' },
          body: {
            ar: 'تُحلّ روابط `TikTok` و`X` عبر واجهاتهما العامة مع `yt-dlp` بديلًا، ويعود `Instagram` بالـ embed أو بشرائح المصدر، وتُعاد كتابة روابط `Reddit` إلى embed. التنزيلات تجري في عملية فرعية بحدود للوقت والحجم، وتُحذف الملفات المؤقتة بعد الإرسال.',
            en: '`TikTok` and `X` links resolve through their public interfaces with `yt-dlp` as a fallback; `Instagram` returns its embed or the source slides, and `Reddit` links are rewritten to the embed. Downloads run in a subprocess with time and size limits, and temporary files are deleted after sending.',
          },
        },
        {
          title: { ar: 'أدوات مجتمع', en: 'Community tools' },
          body: {
            ar: '`XP` والرتبة والسمعة والسحوبات والتذاكر والاستطلاعات و`AFK` و`snipe` والردود التلقائية والرسائل المثبتة و`autorole`.',
            en: '`XP`, ranks, reputation, giveaways, tickets, polls, `AFK`, `snipe`, auto-replies, sticky messages and `autorole`.',
          },
        },
        {
          title: { ar: 'موسيقى اختيارية', en: 'Optional music' },
          body: {
            ar: '`/play` و`/skip` و`/queue` و`/playlist` عبر واجهة الصوت العامة. يبدأ البحث من `SoundCloud`، ويحتاج `YouTube` إلى ملف cookies وبيئة `JavaScript`، ويمكن تعطيل الوحدة بالكامل.',
            en: '`/play`, `/skip`, `/queue` and `/playlist` through the public voice interface. Search starts at `SoundCloud`; `YouTube` needs a cookies file and a `JavaScript` runtime, and the whole cog can be switched off.',
          },
        },
      ],
    },
    {
      kind: 'heading',
      id: 'restraint',
      text: { ar: 'التحفّظ جزء من التصميم', en: 'Restraint is part of the design' },
    },
    {
      kind: 'bullets',
      items: [
        {
          ar: 'النموذج قد يقترح إجراءً إشرافيًا، لكنه لا يُنفَّذ إلا بعد تأكيد صريح من طالبه.',
          en: 'The model may propose a moderation action, but it runs only after the person who asked for it confirms.',
        },
        {
          ar: 'الصلاحية تُفحص عند الطلب وعند التأكيد، لا مرة واحدة عند الإعداد.',
          en: 'Permission is checked when the action is requested and again when it is confirmed — not once at setup.',
        },
        {
          ar: 'الرسائل الخاصة تُسجَّل لأجل مالك البوت وتُحوَّل إليه؛ ينبغي إخبار الأعضاء قبل مراسلة البوت.',
          en: 'Direct messages are logged for the bot owner and forwarded to them; members should be told before messaging the bot.',
        },
        {
          ar: 'لا نسخة احتياطية خارج الخادم بعد: اللقطات محلية عبر `scripts/backup_db.sh`، تُفحص بـ `PRAGMA integrity_check` وتُحفظ بصلاحية `600` لمدة `14` يوماً.',
          en: 'There is no off-server backup yet: snapshots are local via `scripts/backup_db.sh`, verified with `PRAGMA integrity_check`, stored with `600` permissions and kept for `14` days.',
        },
      ],
    },
    { kind: 'cta' },
  ],
};

export const pages: PageDef[] = [
  home,
  {
    slug: 'features',
    eyebrow: { ar: 'المزايا', en: 'Features' },
    h1: { ar: 'ما يفعله أنجل، وحدوده أيضًا.', en: 'What Angel does — and where it stops.' },
    title: { ar: 'المزايا — أنجل', en: 'Features — Angel' },
    description: {
      ar: 'أرشيف قابل للبحث، وذاكرة يكتبها العضو بنفسه، وإشراف محمي، واستخراج وسائط، وأدوات مجتمع — مع قيود معروفة ومكتوبة.',
      en: 'A searchable archive, memory the member writes, guarded moderation, media extraction and community tools — with its limits written down.',
    },
    blocks: [
      {
        kind: 'text',
        text: {
          ar: 'كل ميزة هنا مذكورة في المستودع، وكل رقم في الموقع مولّد من الشيفرة. وما لا يفعله أنجل مكتوب في آخر الصفحة، لا مخفيًا.',
          en: 'Every feature here exists in the repository, and every number on the site is generated from the code. What Angel does not do is written at the end of the page, not hidden.',
        },
      },
      {
        kind: 'entries',
        items: [
          {
            title: { ar: 'محادثة عربية أولًا', en: 'Arabic-first conversation' },
            body: {
              ar: 'يرد أنجل بالعربية افتراضيًا، بشخصية قابلة للضبط، وذاكرة يثبّتها العضو بنفسه بأمر `/memory pin`، وطبقة ذاكرة للتفضيلات الثابتة.',
              en: 'Angel replies in Arabic by default, with a configurable persona, memory the member pins with `/memory pin`, and a memory layer for stable preferences.',
            },
          },
          {
            title: { ar: 'استدعاء محدود النطاق من الأرشيف', en: 'Archive recall, scoped' },
            body: {
              ar: 'تُفهرس الرسائل التي يراها البوت بـ `SQLite FTS5`، وتُقصر النتائج على القنوات التي يستطيع السائل قراءتها، وتبقى الرسائل الخاصة خارج أرشيف السيرفر.',
              en: 'Messages the bot sees are indexed with `SQLite FTS5`; results are restricted to channels the asker can read, and direct messages stay out of the server archive.',
              },
          },
          {
            title: { ar: 'إشراف محمي', en: 'Guarded moderation' },
            body: {
              ar: 'الطرد والحظر والكتم المؤقت والمسح والتحذيرات والقفل والوضع البطيء والأدوار والإعلانات، مع سجل إشراف وحاجز ضد الإغراق. الإجراءات المدمّرة في طابور بتأكيد صريح.',
              en: 'Kick, ban, timeout, purge, warnings, lock, slowmode, roles and announcements, with a moderation log and a flood barrier. Destructive actions queue behind an explicit confirmation.',
            },
          },
          {
            title: { ar: 'استخراج وسائط', en: 'Media extraction' },
            body: {
              ar: 'روابط `TikTok` و`X` تُحلّ عبر الواجهات العامة، و`Instagram` يعود بالـ embed أو بشرائح المصدر، و`Reddit` يُعاد كتابته إلى embed. التنزيلات محكومة بالوقت والحجم، والملفات المؤقتة تُحذف بعد الإرسال.',
              en: '`TikTok` and `X` links resolve through public interfaces; `Instagram` returns its embed or the source slides, and `Reddit` is rewritten to the embed. Downloads are bounded by time and size, and temporary files are deleted after sending.',
            },
          },
          {
            title: { ar: 'أدوات مجتمع', en: 'Community tools' },
            body: {
              ar: '`XP` والرتبة والسمعة والسحوبات والتذاكر والاستطلاعات و`AFK` و`snipe` والردود التلقائية والرسائل المثبتة و`autorole`.',
              en: '`XP`, ranks, reputation, giveaways, tickets, polls, `AFK`, `snipe`, auto-replies, sticky messages and `autorole`.',
            },
          },
          {
            title: { ar: 'موسيقى', en: 'Music' },
            body: {
              ar: '`/play` و`/skip` و`/queue` و`/playlist` عبر واجهة الصوت العامة. البحث يبدأ من `SoundCloud`، ويوتيوب اختياري؛ ويمكن تعطيل الوحدة كاملة أو إزالة يوتيوب وحده.',
              en: '`/play`, `/skip`, `/queue` and `/playlist` through the public voice interface. Search starts at `SoundCloud`; YouTube is optional, and the cog or just YouTube can be turned off.',
            },
          },
          {
            title: { ar: 'إعداد لكل سيرفر وحصة يومية', en: 'Per-server setup and a daily quota' },
            body: {
              ar: '`/setup` يحفظ لهجة السيرفر ومستوى الحماية وحالة مصلّح الروابط، ويتيح `/catchup` تلخيص ما فات العضو من الرسائل مع استبعاد المنسحبين قبل صرف الحصة. حصة الذكاء الاصطناعي اليومية لكل سيرفر تُحسب ذريًا في `SQLite`.',
              en: '`/setup` stores the server dialect, guard level and social-fixer state; `/catchup` summarises what a member missed while dropping opted-out authors before spending quota. Each server’s daily AI quota is accounted atomically in `SQLite`.',
            },
          },
          {
            title: { ar: 'شبكة صادرة محمية', en: 'A guarded outbound network' },
            body: {
              ar: 'كل طلب خارجي يمر عبر طبقة واحدة ترفض العناوين الخاصة وloopback وبيانات metadata، وتعيد التحقق من كل قفزة إعادة توجيه وعند الاتصال نفسه؛ و`yt-dlp` وFFmpeg مقيّدان بقائمة بروتوكولات.',
              en: 'Every outbound request goes through one layer that rejects private addresses, loopback and cloud metadata, re-checks every redirect hop and the connection itself; `yt-dlp` and FFmpeg are constrained by a protocol allowlist.',
            },
          },
          {
            title: { ar: 'مفتوح المصدر', en: 'Open source' },
            body: {
              ar: 'الرخصة `MIT`، والنشر عبر Docker أو Windows أو systemd موثّق في المستودع؛ ويمكنك قراءة الشيفرة كاملة قبل إضافة البوت.',
              en: 'The license is `MIT`, and Docker, Windows and systemd deployment are documented in the repository; you can read the whole source before adding the bot.',
            },
          },
          {
            title: { ar: 'استقلالية اختيارية', en: 'Optional autonomy' },
            body: {
              ar: 'رسائل يبدأها البوت، مع ساعات هادئة، وحدود ساعية ويومية، وحد أدنى لعدد المتحدثين، وفاصل لكل قناة — تُضبط من البيئة لا من الشيفرة.',
              en: 'Bot-initiated messages with quiet hours, hourly and daily limits, a minimum number of speakers and a per-channel gap — configured from the environment, not code.',
            },
          },
          {
            title: { ar: 'ضوابط تشغيل', en: 'Operational controls' },
            body: {
              ar: 'وحدة `systemd`، وبوابة فحص محلية تعمل قبل كل بدء، ولقطة مقاييس، وسكربت نسخ احتياطي موثّق يمكن جدولته من الخادم.',
              en: 'A `systemd` unit, a local check gate that runs before every start, a metrics snapshot and a verified backup script that can be scheduled on the host.',
            },
          },
        ],
      },
      {
        kind: 'heading',
        id: 'limits',
        text: { ar: 'قيود معروفة', en: 'Known limits' },
      },
      {
        kind: 'bullets',
        items: [
          {
            ar: 'لا نسخة احتياطية خارج الخادم بعد.',
            en: 'There is no off-server backup yet.',
          },
          {
            ar: 'فلتر المخرجات طبقة كشف heuristic: يلتقط الحالات الواضحة، ولا يضمن كل صياغة.',
            en: 'The output filter is a heuristic layer: it catches the clear cases, not every phrasing.',
          },
          {
            ar: 'قد يحتاج تشغيل يوتيوب إلى ملف cookies و`Deno`، ويمكن تعطيل يوتيوب أو الوحدة كاملة من البيئة.',
            en: 'YouTube playback may need a cookies file and `Deno`; YouTube or the whole cog can be disabled from the environment.',
          },
          {
            ar: 'الذاكرة مرتبطة بالمستخدم لا بالسيرفر: حقيقة عُرفت في سيرفر تظهر في سيرفر آخر. أما الأرشيف فمحدود بالسيرفر.',
            en: 'Memory follows the user, not the server: a fact learned in one server appears in another. The archive, by contrast, is server-scoped.',
          },
          {
            ar: 'الصوت مشفّر من الطرف إلى الطرف (`DAVE`)؛ اختبار الموسيقى يحتاج عضوًا ثانيًا في القناة.',
            en: 'Voice is end-to-end encrypted (`DAVE`); testing music requires a second member in the channel.',
          },
        ],
      },
      { kind: 'cta' },
    ],
  },
  {
    slug: 'commands',
    eyebrow: { ar: 'الكتالوج', en: 'Catalogue' },
    h1: { ar: 'كل أمر مسجَّل، مع صلاحيته.', en: 'Every registered command, with its permission.' },
    title: { ar: 'الأوامر — أنجل', en: 'Commands — Angel' },
    description: {
      ar: 'كتالوج الأوامر مولّد من شيفرة البوت نفسها: الاسم والوصف والصلاحية والمعاملات، مع بحث وتصفية ونسخ.',
      en: 'The command catalogue generated from the bot source itself: name, description, permission and options, with search, filtering and copy.',
    },
    blocks: [
      {
        kind: 'text',
        text: {
          ar: 'هذه القائمة ليست مكتوبة بيد. يقرأ مولّد البيانات شيفرة البوت ويستخرج ما يُسجَّل فعلًا، ثم يُقارن بعدد سجّله العميل الحقيقي؛ والاختلاف يفشل البناء.',
          en: 'This list is not hand-written. The data generator reads the bot source and extracts what actually registers, then compares it with the count the real client reports; a disagreement fails the build.',
        },
      },
      { kind: 'commands' },
      {
        kind: 'text',
        text: {
          ar: 'الصلاحية بجانب كل أمر هي ما يشترطه الأمر على العضو الذي ينفّذه، لا ما يحتاجه البوت عند الإضافة. ومالك البوت يتجاوز هذه الفحوص.',
          en: 'The permission beside each command is what the command requires from the member who runs it, not what the bot needs at invite time. The bot owner bypasses these checks.',
        },
      },
      {
        kind: 'note',
        text: {
          ar: 'أوامر الموسيقى تُسجَّل عند تفعيل وحدتها، وقوائم السياق الثلاث تعمل من قائمة النقر بزر الفأرة الأيمن على الرسائل.',
          en: 'Music commands register when their cog is enabled, and the three context menus run from the right-click menu on a message.',
        },
      },
      { kind: 'link', label: { ar: 'الصلاحيات التي يطلبها رابط الدعوة', en: 'The permissions the invite link asks for' }, href: '/permissions/' },
    ],
  },
  {
    slug: 'permissions',
    eyebrow: { ar: 'الصلاحيات', en: 'Permissions' },
    h1: { ar: 'ما يطلبه رابط الدعوة، ولماذا.', en: 'What the invite link asks for, and why.' },
    title: { ar: 'الصلاحيات — أنجل', en: 'Permissions — Angel' },
    description: {
      ar: 'الصلاحيات التي يطلبها رابط دعوة أنجل، كل واحدة مع سببها في الشيفرة. لا administrator.',
      en: 'The permissions requested by the Angel invite link, each with the code path that needs it. No administrator.',
    },
    blocks: [
      {
        kind: 'text',
        text: {
          ar: 'رابط الدعوة يطلب الصلاحيات التي تحتاجها مسارات الشيفرة فقط، لا كل ما تستطيع `Discord` منحه. والماسك محسوب من قائمة الأدوار المطلوبة، لا منسوخ من رابط قديم.',
          en: 'The invite link requests only the permissions code paths actually use, not everything `Discord` can grant. The mask is computed from the list of required permissions, not copied from an old link.',
        },
      },
      { kind: 'permissions' },
      {
        kind: 'note',
        text: {
          ar: '`administrator` غير مطلوب عند الإضافة. يظهر في الشيفرة كبوابة على من ينفّذ الأمر، و`Discord` يفحصه على العضو لا على البوت.',
          en: '`administrator` is not requested at invite time. It appears in the source as a gate on who may run a command, and `Discord` checks it against the member, not the bot.',
        },
      },
      {
        kind: 'text',
        text: {
          ar: 'النطاقان المطلوبان هما `bot` و`applications.commands`؛ الثاني يُتيح تسجيل الأوامر في السيرفر.',
          en: 'The two requested scopes are `bot` and `applications.commands`; the second is what allows commands to be registered in the server.',
        },
      },
      { kind: 'cta' },
    ],
  },
  {
    slug: 'how-it-works',
    eyebrow: { ar: 'كيف يعمل', en: 'How it works' },
    h1: { ar: 'مسار واحد واضح، من الحدث إلى الرد.', en: 'One clear path, from event to reply.' },
    title: { ar: 'كيف يعمل — أنجل', en: 'How it works — Angel' },
    description: {
      ar: 'من حدث ديسكورد إلى الموجّه، ثم بوابة الإجراءات أو سلسلة النماذج، ثم فلتر المخرجات — وأرشيف SQLite واحد.',
      en: 'From a Discord event to the router, then the action gate or the model chain, then the output filter — on a single SQLite archive.',
    },
    blocks: [
      {
        kind: 'steps',
        items: [
          {
            title: { ar: 'الحدث يصل', en: 'The event arrives' },
            body: {
              ar: 'تدخل أحداث ديسكورد إلى البوت، ثم يوجّهها مرحل النوايا إلى الأرشيف أو النموذج بحسب الطلب.',
              en: 'Discord events enter the bot, and an intent stage routes each one to the archive or to the model as the request requires.',
            },
          },
          {
            title: { ar: 'السياق يُقرأ', en: 'Context is read' },
            body: {
              ar: 'يقرأ الموجّه الشخصية وذاكرة العضو المثبّتة، ثم يقرر: رد مباشر، أو سلسلة نماذج عند الحاجة إلى نص مولّد، أو إجراء يحتاج بوابة.',
              en: 'The router reads the persona and the memory the member pinned, then decides: a direct reply, the model chain when generated text is needed, or an action that needs the gate.',
            },
          },
          {
            title: { ar: 'بوابة الإجراءات', en: 'The action gate' },
            body: {
              ar: 'تتحقق البوابة من معرّف ديسكورد الثابت للفاعل، ومن الصلاحية المطلوبة، ومن كلمة تدل على النية، قبل أن يصل أي شيء إلى `Discord API`.',
              en: 'The gate checks the actor’s immutable Discord id, the required permission, and a word that signals intent, before anything reaches the `Discord API`.',
            },
          },
          {
            title: { ar: 'فلتر المخرجات', en: 'The output filter' },
            body: {
              ar: 'يزيل `@everyone` والنصوص الشبيهة بالرموز والوسوم المتبقية، ويصحّح ردًّا يدّعي تنفيذ إجراء ما زال في الطابور.',
              en: 'It strips `@everyone`, token-like strings and leftover tags, and corrects a reply that claims an action still sitting in the queue was executed.',
            },
          },
          {
            title: { ar: 'الأرشيف', en: 'The archive' },
            body: {
              ar: 'ملف `SQLite` واحد: `server_messages` للرسائل الخام، وفهرس `FTS5` للبحث. لا طابور خارجي ولا ذاكرة مؤقتة ولا عامل خارجي.',
              en: 'One `SQLite` file: `server_messages` for raw messages and an `FTS5` index for search. No external queue, cache or worker.',
            },
          },
        ],
      },
      {
        kind: 'diagram',
        label: {
          ar: 'مخطط المسار: خمس مراحل، وبوابة تأكيد واحدة بين القرار والتنفيذ.',
          en: 'The pipeline: five stages, and one confirmation gate between the decision and execution.',
        },
      },
      {
        kind: 'heading',
        id: 'operations',
        text: { ar: 'التشغيل', en: 'Operations' },
      },
      {
        kind: 'entries',
        items: [
          {
            title: { ar: 'بوابة قبل كل بدء', en: 'A gate before every start' },
            body: {
              ar: 'تشغّل الوحدة بوابة الفحص قبل بدء الخدمة؛ وإذا فشلت أُلغي البدء بدل أن يُسقِط التحديثُ البوت.',
              en: 'The unit runs the check gate before the service starts; if it fails, startup is cancelled rather than letting a bad deploy take the bot down.',
            },
          },
          {
            title: { ar: 'مهام صيانة قابلة للجدولة', en: 'Schedulable maintenance' },
            body: {
              ar: 'التعلّم من محادثات اليوم، وتحديث ملاحظات الثقافة، والنسخ الاحتياطي، ولقطة المقاييس: سكربتات في المستودع تُشغَّل من مؤقّت على الخادم، لا مهام مخفية داخل العملية.',
              en: 'Learning from the day’s conversations, refreshing culture notes, backups and the metrics snapshot are scripts in the repository, run from a host timer — not hidden tasks inside the process.',
            },
          },
          {
            title: { ar: 'نسخ احتياطي موثّق', en: 'Verified backups' },
            body: {
              ar: '`scripts/backup_db.sh` ينشئ نسخة متسقة بـ `sqlite3 .backup`، يتحقق منها بـ `PRAGMA integrity_check`، يحفظها بصلاحية `600` ويحتفظ بها `14` يومًا. لا نسخة خارج الخادم بعد.',
              en: '`scripts/backup_db.sh` writes a consistent copy with `sqlite3 .backup`, verifies it with `PRAGMA integrity_check`, stores it `600` and keeps it for `14` days. There is no off-host copy yet.',
            },
          },
        ],
      },
      { kind: 'cta' },
    ],
  },
  {
    slug: 'security',
    eyebrow: { ar: 'الأمان', en: 'Security' },
    h1: { ar: 'التحفّظ حيث لا يُرى: الفحوص والبوابات.', en: 'Restraint where it is invisible: checks and gates.' },
    title: { ar: 'الأمان — أنجل', en: 'Security — Angel' },
    description: {
      ar: 'فحوص المالك بمعرّفات ثابتة، وتأكيد صريح للإجراءات المدمّرة، ونطاق أرشيف محدود، وفلتر مخرجات، ومنع shell.',
      en: 'Owner checks on immutable ids, explicit confirmation for destructive actions, a scoped archive, an output filter and no shell.',
    },
    blocks: [
      {
        kind: 'entries',
        items: [
          {
            title: { ar: 'هوية المالك بالمعرّف', en: 'The owner is an id, not a name' },
            body: {
              ar: 'تعتمد فحوص المالك على معرّفات ديسكورد الثابتة، لا على الأسماء أو الألقاب التي يمكن انتحالها.',
              en: 'Owner checks rely on immutable Discord ids, never on display names or nicknames that can be imitated.',
            },
          },
          {
            title: { ar: 'تأكيد صريح للإجراءات المدمّرة', en: 'Explicit confirmation for destructive actions' },
            body: {
              ar: 'الإجراءات التي يقترحها النموذج (`BAN` و`KICK` و`PURGE` و`DELETE_CHANNEL`) تُوضع في طابور، ويتطلب كل منها أن يكتب الشخص نفسه الذي طلبه «تأكيد» خلال 60 ثانية. كلمة الإلغاء تمسح الطلب، والصلاحية تُراجَع عند التأكيد.',
              en: 'Actions the model proposes (`BAN`, `KICK`, `PURGE`, `DELETE_CHANNEL`) are queued, and each requires the person who requested it to type “confirm” within 60 seconds. A cancel word clears it, and permission is re-checked on confirmation.',
            },
          },
          {
            title: { ar: 'نطاق الأرشيف', en: 'Archive scope' },
            body: {
              ar: 'استدعاء الأرشيف محدود بالقنوات التي يستطيع السائل قراءتها، والرسائل الخاصة مستبعدة من أرشيف السيرفر.',
              en: 'Archive recall is limited to channels the asker can read, and direct messages are excluded from the server archive.',
            },
          },
          {
            title: { ar: 'الرسائل الخاصة معلَنة', en: 'Direct messages are disclosed' },
            body: {
              ar: 'تُسجَّل الرسائل الخاصة لأجل المالكة: اسم المرسل والنص وروابط المرفقات ورد أنجل في جدول `dm_logs`، وتُحوَّل الرسالة إلى خاص المالكة. ينبغي إخبار الأعضاء بذلك قبل مراسلة البوت.',
              en: 'Direct messages are logged for the owner — sender name, text, attachment links and Angel’s reply in the `dm_logs` table — and forwarded to the owner’s DMs. Members should be told before messaging the bot.',
            },
          },
          {
            title: { ar: 'شبكة صادرة محمية', en: 'A guarded outbound network' },
            body: {
              ar: 'طلبات الوسائط تمر عبر طبقة واحدة: صيغة رابط صارمة، رفض العناوين الخاصة وloopback و`169.254.169.254` وIPv6 المحمّلة، تحقق DNS من كل عنوان، وإعادة تحقق عند الاتصال وعند كل قفزة إعادة توجيه. و`yt-dlp` لا يستقبل هدفًا يبدأ بـ`-`، وFFmpeg مقيّد بقائمة بروتوكولات.',
              en: 'Media requests go through one layer: strict URL syntax, rejection of private addresses, loopback, `169.254.169.254` and wrapped IPv6, DNS validation of every address, and re-checks at connect time and on every redirect hop. `yt-dlp` never receives a target beginning with `-`, and FFmpeg is constrained by a protocol allowlist.',
            },
          },
          {
            title: { ar: 'انسحاب مغلق افتراضيًا', en: 'Opt-out fails closed' },
            body: {
              ar: 'من يستخدم `/data delete` يبقى منسحبًا. أي خطأ في قراءة التفضيل يُعامل كانسحاب، فلا تُسجَّل رسالته ولا تظهر في `snipe` أو سجل الإشراف أو سياق المحادثة أو أهداف الاستقلالية.',
              en: 'Anyone who runs `/data delete` stays opted out. Any failure while reading the preference is treated as opted out, so their message is not logged and does not reach `snipe`, the modlog, ambient context or autonomy targets.',
            },
          },
          {
            title: { ar: 'تنقيح الأسرار', en: 'Secret redaction' },
            body: {
              ar: 'فلتر المخرجات يحجب رموز Discord وGitHub وBearer ومفاتيح `AIza` و`sk-` وصيغ `TOKEN=...` قبل الإرسال، ويبطل منشنات الرتب و`@everyone`.',
              en: 'The output filter redacts Discord, GitHub and Bearer tokens, `AIza`/`sk-` keys and `TOKEN=...` lines before sending, and neutralises role mentions and `@everyone`.',
            },
          },
          {
            title: { ar: 'فلتر المخرجات', en: 'Output filter' },
            body: {
              ar: 'يزيل `@everyone` والنصوص الشبيهة بالرموز والوسوم المتبقية، ويصحّح ردًّا يدّعي تنفيذ إجراء ما زال في الطابور.',
              en: 'It removes `@everyone`, token-like strings and leftover tags, and corrects a reply that claims an action still in the queue was executed.',
            },
          },
          {
            title: { ar: 'لا shell في مسارات التشغيل', en: 'No shell on the runtime paths' },
            body: {
              ar: 'ترفض بوابة الفحص الثابتة استخدام `create_subprocess_shell` و`os.system` و`os.popen` و`shell=True` في مسارات التشغيل.',
              en: 'The static gate rejects `create_subprocess_shell`, `os.system`, `os.popen` and `shell=True` on runtime paths.',
            },
          },
        ],
      },
      {
        kind: 'heading',
        id: 'report',
        text: { ar: 'الإبلاغ عن ثغرة', en: 'Reporting a vulnerability' },
      },
      {
        kind: 'text',
        text: {
          ar: 'لا تفتح بلاغًا عامًا. استخدم تقرير الثغرات الخاص في `GitHub` من تبويب Security. وإن لم يكن الزر متاحًا، افتح بلاغًا يقول فقط إن لديك تقريرًا أمنيًا، دون تفاصيل.',
          en: 'Do not open a public issue. Use GitHub’s private vulnerability reporting from the Security tab. If the button is unavailable, open an issue that says only that you have a security report, with no details.',
        },
      },
      {
        kind: 'link',
        label: { ar: 'سياسة الأمان في المستودع', en: 'The security policy in the repository' },
        href: 'https://github.com/Certainty7/angelbot/blob/master/SECURITY.md',
      },
      {
        kind: 'note',
        text: {
          ar: 'هذا مشروع بمشرف واحد: تُقرأ البلاغات عند الوصول، ويصل الإصلاح إلى `master` عندما يكون جاهزًا. أمهل المشرف وقتًا قبل الكتابة عن المشكلة علنًا.',
          en: 'This is a single-maintainer project: reports are read when they arrive, and a fix lands on `master` when it is ready. Give the maintainer time before writing about the issue publicly.',
        },
      },
    ],
  },
  {
    slug: 'privacy',
    eyebrow: { ar: 'الخصوصية', en: 'Privacy' },
    h1: { ar: 'ما يُخزَّن، وأين، ولماذا.', en: 'What is stored, where, and why.' },
    title: { ar: 'الخصوصية — أنجل', en: 'Privacy — Angel' },
    description: {
      ar: 'أرشيف محلي على خادم البوت لسنة واحدة، وذاكرة يكتبها العضو بنفسه، وسجل للرسائل الخاصة لأجل المالك، وموقع لا يتتبّع.',
      en: 'A local archive on the bot host kept for one year, memory the member writes themselves, owner-only DM logs, and a website that does not track.',
    },
    blocks: [
      {
        kind: 'entries',
        items: [
          {
            title: { ar: 'ما يُؤرشف', en: 'What is archived' },
            body: {
              ar: 'الرسائل التي يراها البوت في القنوات التي يستطيع قراءتها، مقتطعة عند 1500 حرف مع بياناتها الوصفية. تُحفظ في `server_messages` وتُفهرس في `FTS5` للبحث، وتبقى سنة واحدة ثم تُحذف تلقائياً. الأرشيف محدود بالسيرفر.',
              en: 'The messages the bot sees in channels it can read, truncated at 1500 characters with their metadata. They are stored in `server_messages` and indexed in `FTS5` for search, kept for one year and then deleted automatically. The archive is server-scoped.',
            },
          },
          {
            title: { ar: 'الذاكرة الشخصية', en: 'Personal memory' },
            body: {
              ar: 'لا يبني أنجل ملفاً تعريفياً عن أحد، ولا يستنتج صفاتك من رسائلك. ما يُحفظ عنك هو ما تكتبه بنفسك بأمر `/memory pin` فقط، ويمكنك مسحه بـ`/memory forget` أو حذفه كله بـ`/data`.',
              en: 'Angel builds no profile of anyone and infers nothing about you from your messages. The only memory stored is what you write yourself with `/memory pin`; `/memory forget` removes one item and `/data` erases everything.',
            },
          },
          {
            title: { ar: 'محادثتك مع البوت', en: 'Your chat with the bot' },
            body: {
              ar: 'تُحفظ آخر `50` رسالة لكل عضو في محادثته المباشرة مع البوت، مع ملخص قصير لها، لتسيير الحوار. يمسحها `/memory clear` أو `/data`.',
              en: 'The last `50` messages of each member’s direct chat with the bot are kept, with a short summary, to keep the conversation coherent. `/memory clear` or `/data` removes them.',
            },
          },
          {
            title: { ar: 'الرسائل الخاصة', en: 'Direct messages' },
            body: {
              ar: 'تُسجَّل الرسائل الخاصة المرسلة إلى البوت لأجل مالكه وتُحوَّل إليه، وتبقى `30` يوماً ثم تُحذف تلقائياً. لا تراسل البوت إن لم تكن مرتاحاً لذلك؛ وينبغي أن يُخبر الأعضاء بذلك في السيرفر.',
              en: 'Direct messages sent to the bot are logged for its owner and forwarded to them, kept for `30` days and then deleted automatically. Do not message the bot if you are not comfortable with that; servers should tell their members.',
            },
          },
          {
            title: { ar: 'النسخ الاحتياطية', en: 'Backups' },
            body: {
              ar: 'لقطات دورية من قاعدة البيانات تُنشأ بـ `scripts/backup_db.sh` وتُحفظ بصلاحية `600`، ويُحتفظ بها `14` يوماً ثم تُحذف. تحتوي الرسائل والذاكرة، ولا تُنسخ خارج الخادم. الحذف يصل إلى هذه اللقطات خلال دورة الاحتفاظ نفسها.',
              en: 'Periodic database snapshots made with `scripts/backup_db.sh`, stored with `600` permissions and kept for `14` days before deletion. They contain messages and memory, and are never copied off the host. Deletions reach these snapshots within that retention window.',
            },
          },
          {
            title: { ar: 'هذا الموقع', en: 'This website' },
            body: {
              ar: 'موقع ثابت: لا تحليلات، ولا إعلانات، ولا أدوات تتبّع، ولا طلبات إلى نطاقات خارجية. لا يضع الموقع أي كوكيز؛ وتفضيل المظهر يُحفظ في `localStorage` داخل متصفحك فقط. الخطوط والأصول مستضافة ذاتيًا.',
              en: 'A static site: no analytics, no ads, no tracking tools, no requests to third-party domains. It sets no cookies; your theme preference is stored in `localStorage` in your browser only. Fonts and assets are self-hosted.',
            },
          },
          {
            title: { ar: 'روابط خارجية', en: 'External links' },
            body: {
              ar: 'الروابط إلى `GitHub` أو `Discord` تفتح مواقع أخرى، وتخضع لسياساتها لا لهذه الصفحة.',
              en: 'Links to `GitHub` or `Discord` open other sites and are governed by their policies, not this page.',
            },
          },
        ],
      },
      {
        kind: 'entries',
        items: [
          {
            title: { ar: 'بياناتك، بأمر واحد', en: 'Your data, in one command' },
            body: {
              ar: '`/data` يعرض لك ما يُخزَّن عنك: عدد رسائلك المؤرشفة، ورسائل محادثتك مع البوت، والملاحظات المحفوظة، ورسائلك الخاصة المسجلة. و`/data` مع خيار الحذف يمسحها كلها ويوقف الحفظ التلقائي عنك. لا نموذج ولا بريد ولا انتظار.',
              en: '`/data` shows what is stored about you: archived messages, your chat with the bot, saved notes and logged direct messages. The delete option erases all of it and stops future storage. No form, no email, no waiting.',
            },
          },
        ],
      },
      {
        kind: 'text',
        text: {
          ar: 'هذا الموقع لا يحتوي نموذج تواصل ولا يجمع أي إدخال من الزائر. لإدارة بياناتك داخل البوت استخدم أمر `/data` في السيرفر أو في الخاص؛ وإن تعذّر ذلك، تواصل مع مالك البوت الذي أضافه إلى سيرفرك.',
          en: 'This site has no contact form and collects no visitor input. Use the `/data` command in the server or in DMs to manage your data; if that is unavailable, contact the owner of the bot in your server.',
        },
      },
    ],
  },
  {
    slug: 'faq',
    eyebrow: { ar: 'الأسئلة', en: 'FAQ' },
    h1: { ar: 'أسئلة تُسأل فعلًا.', en: 'Questions people actually ask.' },
    title: { ar: 'الأسئلة الشائعة — أنجل', en: 'FAQ — Angel' },
    description: {
      ar: 'الدعوة، والقراءة، والرسائل الخاصة، والإشراف، والموسيقى، والتتبّع، والإبلاغ عن الثغرات.',
      en: 'Inviting, reading, direct messages, moderation, music, tracking and vulnerability reports.',
    },
    blocks: [
      {
        kind: 'faq',
        items: [
          {
            q: { ar: 'هل أحتاج حسابًا لإضافة أنجل؟', en: 'Do I need an account to add Angel?' },
            a: {
              ar: 'لا. رابط الدعوة مفتوح، ولا يطلب هذا الموقع أي حساب أو تسجيل.',
              en: 'No. The invite link is open, and this website asks for no account or sign-up.',
            },
          },
          {
            q: { ar: 'هل يقرأ أنجل كل الرسائل؟', en: 'Does Angel read every message?' },
            a: {
              ar: 'يقرأ ما تسمح به صلاحياته في القنوات التي أُضيف إليها، والرسائل الخاصة المرسلة إليه. يحتاج البوت إلى نية `Message Content` ليعمل.',
              en: 'It reads what its permissions allow in the channels it was added to, plus direct messages sent to it. The bot needs the `Message Content` intent to work.',
            },
          },
          {
            q: { ar: 'هل تُسجَّل رسائلي الخاصة؟', en: 'Are my direct messages logged?' },
            a: {
              ar: 'نعم، الرسائل الخاصة المرسلة إلى البوت تُسجَّل لأجل مالكه وتُحوَّل إليه. إن لم تكن مرتاحًا لذلك، لا تراسل البوت.',
              en: 'Yes. Direct messages sent to the bot are logged for its owner and forwarded to them. If you are not comfortable with that, do not message the bot.',
            },
          },
          {
            q: { ar: 'من يستطيع تنفيذ إجراء إشرافي؟', en: 'Who can run a moderation action?' },
            a: {
              ar: 'من يملك الصلاحية المطلوبة في السيرفر، أو مالك البوت. والإجراءات المدمّرة تحتاج تأكيدًا صريحًا خلال 60 ثانية.',
              en: 'Anyone holding the required permission in the server, or the bot owner. Destructive actions need an explicit confirmation within 60 seconds.',
            },
          },
          {
            q: { ar: 'هل يعمل الموسيقى دائمًا؟', en: 'Does music always work?' },
            a: {
              ar: 'البحث يبدأ من `SoundCloud`. تشغيل يوتيوب يحتاج ملف cookies و`Deno`، ويمكن لمالك البوت تعطيل يوتيوب أو الوحدة كاملة.',
              en: 'Search starts at `SoundCloud`. YouTube playback needs a cookies file and `Deno`, and the bot owner can disable YouTube or the whole cog.',
            },
          },
          {
            q: { ar: 'هل يتتبّع هذا الموقع زيارتي؟', en: 'Does this website track me?' },
            a: {
              ar: 'لا. لا تحليلات ولا إعلانات ولا خطوط من CDN خارجي؛ وتفضيل المظهر يُحفظ في متصفحك عبر `localStorage` فقط.',
              en: 'No. There are no analytics, no ads and no external CDN fonts; your theme preference is stored in your browser’s `localStorage` only.',
            },
          },
          {
            q: { ar: 'كيف أحذف بياناتي؟', en: 'How do I delete my data?' },
            a: {
              ar: 'أمر `/data` يحذف بياناتك بنفسك: رسائلك المؤرشفة ومحادثتك وملاحظاتك ورسائلك الخاصة المسجلة، ويوقف الحفظ التلقائي عنك. لا حاجة لمراسلة أحد؛ وتبقى النسخ الاحتياطية المحلية حتى دورة الاحتفاظ.',
              en: 'The `/data` command deletes your data yourself: archived messages, conversation, notes and logged direct messages, and it stops automatic storage. No need to contact anyone; local backups keep the rows until their retention cycle.',
            },
          },
          {
            q: { ar: 'كيف أبلّغ عن ثغرة؟', en: 'How do I report a vulnerability?' },
            a: {
              ar: 'عبر تقرير الثغرات الخاص في `GitHub` من تبويب Security، لا في بلاغ عام. التفاصيل في سياسة الأمان.',
              en: 'Through GitHub’s private vulnerability reporting on the Security tab, never a public issue. Details are in the security policy.',
            },
          },
        ],
      },
      { kind: 'link', label: { ar: 'سياسة الأمان', en: 'Security policy' }, href: 'https://github.com/Certainty7/angelbot/blob/master/SECURITY.md' },
      { kind: 'cta' },
    ],
  },
  {
    slug: 'changelog',
    eyebrow: { ar: 'سجل التغييرات', en: 'Changelog' },
    h1: { ar: 'ما تغيّر، إصدارًا بعد إصدار.', en: 'What changed, release by release.' },
    title: { ar: 'سجل التغييرات — أنجل', en: 'Changelog — Angel' },
    description: {
      ar: 'الإصدارات المنشورة، مولّدة من ملف سجل التغييرات في المستودع بالعربية والإنجليزية.',
      en: 'Published releases, generated from the repository changelog in Arabic and English.',
    },
    blocks: [
      {
        kind: 'text',
        text: {
          ar: 'كل إصدار هنا مأخوذ من `CHANGELOG.md` و`CHANGELOG.ar.md` في المستودع نفسه؛ لا تُكتب الإصدارات بيد في هذه الصفحة. وأي تغيير في الملفين يُحدّث الصفحة عند البناء.',
          en: 'Every release here comes from `CHANGELOG.md` and `CHANGELOG.ar.md` in the repository itself; the page does not invent releases. A change to either file updates the page at build time.',
        },
      },
      { kind: 'changelog' },
      {
        kind: 'link',
        label: { ar: 'كل الإصدارات على GitHub', en: 'All releases on GitHub' },
        href: 'https://github.com/Certainty7/angelbot/releases',
      },
      {
        kind: 'link',
        label: { ar: 'سجل الإيداعات الكامل', en: 'The full commit history' },
        href: 'https://github.com/Certainty7/angelbot/commits/master',
      },
    ],
  },
];

