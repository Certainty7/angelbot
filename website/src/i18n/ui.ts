export type Lang = 'ar' | 'en';
export type Loc = { ar: string; en: string };

export const LANGS: Lang[] = ['ar', 'en'];

/** Arabic is the primary locale and lives at the root; English mirrors it under /en/. */
export function href(lang: Lang, slug = ''): string {
  const prefix = lang === 'en' ? '/en/' : '/';
  return slug ? `${prefix}${slug}/` : prefix;
}

export const site = {
  origin: 'https://angel.aetherisnode.cloud',
  name: { ar: 'أنجل', en: 'Angel' },
  tagline: {
    ar: 'بوت ديسكورد عربي لسيرفرات المجتمع.',
    en: 'An Arabic Discord bot for community servers.',
  },
  repository: 'https://github.com/Certainty7/angelbot',
};

type NavItem = { slug: string; label: Loc };

/** Primary navigation. Privacy and the changelog live in the footer to keep the bar editorial. */
export const nav: NavItem[] = [
  { slug: 'features', label: { ar: 'المزايا', en: 'Features' } },
  { slug: 'commands', label: { ar: 'الأوامر', en: 'Commands' } },
  { slug: 'permissions', label: { ar: 'الصلاحيات', en: 'Permissions' } },
  { slug: 'how-it-works', label: { ar: 'كيف يعمل', en: 'How it works' } },
  { slug: 'security', label: { ar: 'الأمان', en: 'Security' } },
  { slug: 'faq', label: { ar: 'الأسئلة', en: 'FAQ' } },
];

export const ui = {
  skip: { ar: 'تخطَّ إلى المحتوى', en: 'Skip to content' },
  home: { ar: 'الصفحة الرئيسية', en: 'Home' },
  primaryNav: { ar: 'التنقّل الرئيسي', en: 'Primary' },
  openMenu: { ar: 'فتح القائمة', en: 'Open menu' },
  closeMenu: { ar: 'إغلاق القائمة', en: 'Close menu' },
  theme: { ar: 'المظهر', en: 'Theme' },
  themeToDark: { ar: 'التبديل إلى مظهر الليل الوردي', en: 'Switch to Rose Night' },
  themeToLight: { ar: 'التبديل إلى مظهر اللؤلؤة', en: 'Switch to Pearl Light' },
  language: { ar: 'English', en: 'العربية' },
  languageHint: { ar: 'عرض الصفحة بالإنجليزية', en: 'View this page in Arabic' },
  invite: { ar: 'أضف أنجل إلى سيرفرك', en: 'Add Angel to your server' },
  inviteShort: { ar: 'أضف أنجل', en: 'Add Angel' },
  footerProduct: { ar: 'المنتج', en: 'Product' },
  footerTrust: { ar: 'الثقة', en: 'Trust' },
  footerRepo: { ar: 'المستودع', en: 'Repository' },
  footerPrivacy: { ar: 'الخصوصية', en: 'Privacy' },
  footerChangelog: { ar: 'سجل التغييرات', en: 'Changelog' },
  footerNote: {
    ar: 'موقع ثابت بلا تتبّع ولا إعلانات. الخطوط والأصول مستضافة ذاتيًا.',
    en: 'A static site with no tracking and no ads. Fonts and assets are self-hosted.',
  },
  copyright: {
    ar: 'أنجل — جميع الحقوق محفوظة.',
    en: 'Angel — all rights reserved.',
  },
  browse: { ar: 'تصفّح الأوامر', en: 'Browse the commands' },
  heroNote: { ar: 'مفتوح للإضافة — لا حساب مطلوب.', en: 'Open to invite — no account needed.' },
  ctaTitle: { ar: 'أضف أنجل، أو اقرأ الأوامر أولًا.', en: 'Add Angel, or read the commands first.' },
  ctaBody: {
    ar: 'رابط الدعوة لا يطلب `administrator`، والصلاحيات منشورة قبل الإضافة.',
    en: 'The invite link does not request `administrator`, and every permission is published before you add it.',
  },
  search: { ar: 'ابحث في الأوامر', en: 'Search commands' },
  searchPlaceholder: { ar: 'اسم الأمر أو وصفه أو صلاحية', en: 'Command name, description or permission' },
  filterLabel: { ar: 'تصفية حسب الفئة', en: 'Filter by category' },
  all: { ar: 'الكل', en: 'All' },
  noResults: { ar: 'لا أمر يطابق هذا البحث.', en: 'No command matches this search.' },
  ownerOnly: { ar: 'للمالكة فقط', en: 'Owner only' },
  ownerSection: { ar: 'أدوات المالكة', en: 'Owner tools' },
  ownerSectionNote: {
    ar: 'أوامر مسجّلة كغيرها، لكن معالجها يرفض كل من ليس المالكة قبل أن ينفّذ أي شيء. لا تُعرض لها شرائح صلاحيات: القيمة الظاهرة في الشيفرة تحقّق من رتبة المستدعي، لا صلاحية يطلبها البوت.',
    en: 'Registered like every other command, but the handler refuses anyone who is not the owner before it does any work. No permission chips are shown: the value in the source gates the invoking member, it is not something the bot requests.',
  },
  contextMenu: { ar: 'قائمة سياق', en: 'Context menu' },
  optionsLabel: { ar: 'المعاملات', en: 'Options' },
  noOptions: { ar: 'لا معاملات لهذا الأمر.', en: 'This command takes no options.' },
  required: { ar: 'مطلوب', en: 'required' },
  optional: { ar: 'اختياري', en: 'optional' },
  copy: { ar: 'نسخ', en: 'Copy' },
  copied: { ar: 'تم النسخ', en: 'Copied' },
  permissionCol: { ar: 'الصلاحية', en: 'Permission' },
  whyCol: { ar: 'السبب في الشيفرة', en: 'Why the code needs it' },
  permissionTableCaption: { ar: 'الصلاحيات التي يطلبها رابط الدعوة', en: 'Permissions requested by the invite link' },
};
