// ข้อมูลคณะ + ภาค/สาขาของมหาวิทยาลัยมหิดล
// ที่มา: https://mahidol.ac.th/th/faculty-history/
// เก็บเป็นรหัสใน DB (เช่น EG/CO) แสดงชื่อเต็มใน UI
// เหตุผล: รหัสสั้น จำง่าย ค้นหา/สถิติได้ คนถามกัน "ภาค CO" ก็ตอบได้เลย

export interface Department {
  code: string;
  name: string;
  nameEn: string;
  abbr?: string; // ตัวย่อทางการ เช่น EGCO, CI (ไม่ระบุ → ใช้ facCode+deptCode)
}

export interface Faculty {
  code: string;
  name: string;
  nameEn: string;
  departments: Department[];
}

export const FACULTIES: Faculty[] = [
  {
    code: "SI",
    name: "คณะแพทยศาสตร์ศิริราชพยาบาล",
    nameEn: "Faculty of Medicine Siriraj Hospital",
    departments: [
      { code: "MD", name: "แพทยศาสตร์", nameEn: "Medicine" },
    ],
  },
  {
    code: "RA",
    name: "คณะแพทยศาสตร์โรงพยาบาลรามาธิบดี",
    nameEn: "Faculty of Medicine Ramathibodi Hospital",
    departments: [
      { code: "MD", name: "แพทยศาสตร์", nameEn: "Medicine" },
    ],
  },
  {
    code: "DT",
    name: "คณะทันตแพทยศาสตร์",
    nameEn: "Faculty of Dentistry",
    departments: [
      { code: "DT", name: "ทันตกรรม", nameEn: "Dentistry" },
      { code: "PH", name: "ทันตสุขศาสตร์", nameEn: "Dental Public Health" },
      { code: "PR", name: "ทันตกรรมประดิษฐ์", nameEn: "Prosthodontics" },
      { code: "OR", name: "ทันตกรรมจัดฟัน", nameEn: "Orthodontics" },
      { code: "PE", name: "ปริทันตวิทยา", nameEn: "Periodontology" },
    ],
  },
  {
    code: "PH",
    name: "คณะเภสัชศาสตร์",
    nameEn: "Faculty of Pharmacy",
    // 1 หลักสูตรปริญญาตรี (Pharm.D. 6 ปี) + 2 สาขาเน้นในชั้นปีที่ 5
    // ที่มา: pharmacy.mahidol.ac.th
    departments: [
      { code: "PC", name: "สาขาเน้นการบริบาลทางเภสัชกรรม", nameEn: "Pharmaceutical Care" },
      { code: "PS", name: "สาขาเน้นเภสัชกรรมอุตสาหการ", nameEn: "Pharmaceutical Science" },
    ],
  },
  {
    code: "NS",
    name: "คณะพยาบาลศาสตร์",
    nameEn: "Faculty of Nursing",
    departments: [
      { code: "NS", name: "พยาบาลศาสตร์", nameEn: "Nursing" },
    ],
  },
  {
    code: "SP",
    name: "คณะสาธารณสุขศาสตร์",
    nameEn: "Faculty of Public Health",
    departments: [
      { code: "PH", name: "สาธารณสุขศาสตร์", nameEn: "Public Health" },
      { code: "EP", name: "ระบาดวิทยา", nameEn: "Epidemiology" },
      { code: "NU", name: "โภชนาการ", nameEn: "Nutrition" },
      { code: "OH", name: "อาชีวอนามัย", nameEn: "Occupational Health" },
      { code: "HE", name: "สุขศึกษา", nameEn: "Health Education" },
    ],
  },
  {
    code: "MT",
    name: "คณะเทคนิคการแพทย์",
    nameEn: "Faculty of Medical Technology",
    departments: [
      { code: "MT", name: "เทคนิคการแพทย์", nameEn: "Medical Technology" },
    ],
  },
  {
    code: "TM",
    name: "คณะเวชศาสตร์เขตร้อน",
    nameEn: "Faculty of Tropical Medicine",
    departments: [
      { code: "TM", name: "เวชศาสตร์เขตร้อน", nameEn: "Tropical Medicine" },
      { code: "PA", name: "ปรสิตวิทยา", nameEn: "Parasitology" },
      { code: "EN", name: "กีฏวิทยา", nameEn: "Entomology" },
      { code: "NU", name: "โภชนาการ", nameEn: "Nutrition" },
    ],
  },
  {
    code: "PT",
    name: "คณะกายภาพบำบัด",
    nameEn: "Faculty of Physical Therapy",
    departments: [
      { code: "PT", name: "กายภาพบำบัด", nameEn: "Physical Therapy" },
    ],
  },
  {
    code: "SC",
    name: "คณะวิทยาศาสตร์",
    nameEn: "Faculty of Science",
    // 12 ภาควิชา + สาขาวิชาปริญญาตรี (ทั้งไทยและนานาชาติ)
    // ที่มา: science.mahidol.ac.th
    departments: [
      // ── หลักสูตรปกติ ──
      { code: "BI", name: "สาขาวิชาชีววิทยา", nameEn: "Biology" },
      { code: "BT", name: "สาขาวิชาเทคโนโลยีชีวภาพ", nameEn: "Biotechnology" },
      { code: "CH", name: "สาขาวิชาเคมี", nameEn: "Chemistry" },
      { code: "MA", name: "สาขาวิชาคณิตศาสตร์", nameEn: "Mathematics" },
      { code: "PS", name: "สาขาวิชาพฤกษศาสตร์", nameEn: "Plant Science" },
      { code: "PH", name: "สาขาวิชาฟิสิกส์", nameEn: "Physics" },
      // ── หลักสูตรนานาชาติ ──
      { code: "AM", name: "สาขาวิชาคณิตศาสตร์ประกันภัย (นานาชาติ)", nameEn: "Actuarial Mathematics" },
      { code: "BE", name: "สาขาวิชาทรัพยากรชีวภาพและชีววิทยาสภาวะแวดล้อม (นานาชาติ)", nameEn: "Bioresources and Environmental Biology" },
      { code: "BM", name: "สาขาวิชาวิทยาศาสตร์ชีวการแพทย์ (นานาชาติ)", nameEn: "Biomedical Science" },
      { code: "CI", name: "สาขาวิชานวัตกรรมเคมีและเทคโนโลยี (นานาชาติ)", nameEn: "Chemistry Innovation and Technology" },
      { code: "IM", name: "สาขาวิชาคณิตศาสตร์อุตสาหการและวิทยาการข้อมูล (นานาชาติ)", nameEn: "Industrial Mathematics and Data Science" },
      { code: "BN", name: "สาขาวิชาชีวนวัตกรรม (นานาชาติ)", nameEn: "Bioinnovation" },
      { code: "MN", name: "สาขาวิชาวัสดุศาสตร์และวิศวกรรมนาโน (นานาชาติ)", nameEn: "Materials Science and Nano Engineering" },
    ],
  },
  {
    code: "EG",
    name: "คณะวิศวกรรมศาสตร์",
    nameEn: "Faculty of Engineering",
    // คณะวิศวฯ มหิดลมี 9 หลักสูตรปริญญาตรี
    // ★ ตัวย่อภาควิชา = EG + ตัวย่อสาขา (ยืนยันจาก eg.mahidol.ac.th/dept/*)
    //   เช่น EGCO, EGEE, EGCE, EGIE, EGME, EGCG, EGBE
    departments: [
      // ── หลักสูตรปกติ (ภาควิชา) ──
      { code: "ME", name: "สาขาวิชาวิศวกรรมเครื่องกล", nameEn: "Mechanical Engineering", abbr: "EGME" },
      { code: "CHE", name: "สาขาวิชาวิศวกรรมเคมี", nameEn: "Chemical Engineering", abbr: "EGCHE" },
      { code: "EE", name: "สาขาวิชาวิศวกรรมไฟฟ้า", nameEn: "Electrical Engineering", abbr: "EGEE" },
      { code: "IE", name: "สาขาวิชาวิศวกรรมอุตสาหการ", nameEn: "Industrial Engineering", abbr: "EGIE" },
      { code: "CO", name: "สาขาวิชาวิศวกรรมคอมพิวเตอร์", nameEn: "Computer Engineering", abbr: "EGCO" },
      { code: "CE", name: "สาขาวิชาวิศวกรรมโยธา", nameEn: "Civil Engineering", abbr: "EGCE" },
      // ── หลักสูตรนานาชาติ ──
      { code: "TC", name: "สาขาวิชาวิศวกรรมไฟฟ้าสื่อสาร", nameEn: "Electrical and Communication Engineering", abbr: "EGTC" },
      { code: "BE", name: "สาขาวิชาวิศวกรรมชีวการแพทย์", nameEn: "Biomedical Engineering", abbr: "EGBE" },
      { code: "CI", name: "สาขาวิชาวิศวกรรมคอมพิวเตอร์ (หลักสูตรนานาชาติ)", nameEn: "Computer Engineering International Program", abbr: "CI" },
    ],
  },
  {
    code: "VT",
    name: "คณะสัตวแพทยศาสตร์",
    nameEn: "Faculty of Veterinary Medicine",
    departments: [
      { code: "VT", name: "สัตวแพทยศาสตร์", nameEn: "Veterinary Medicine" },
      { code: "AS", name: "การสัตวบาล", nameEn: "Animal Science" },
      { code: "VS", name: "สัตวศาสตร์", nameEn: "Veterinary Science" },
    ],
  },
  {
    code: "SH",
    name: "คณะสังคมศาสตร์และมนุษยศาสตร์",
    nameEn: "Faculty of Social Sciences and Humanities",
    departments: [
      { code: "SS", name: "สังคมศาสตร์", nameEn: "Social Sciences" },
      { code: "AH", name: "ศิลปศาสตร์และมนุษยศาสตร์", nameEn: "Humanities" },
      { code: "ED", name: "การศึกษา", nameEn: "Education" },
    ],
  },
  {
    code: "AS",
    name: "คณะศิลปศาสตร์",
    nameEn: "Faculty of Arts",
    departments: [
      { code: "AH", name: "ศิลปศาสตร์และมนุษยศาสตร์", nameEn: "Arts and Humanities" },
      { code: "EN", name: "ภาษาอังกฤษ", nameEn: "English" },
      { code: "TH", name: "ภาษาไทย", nameEn: "Thai" },
    ],
  },
  {
    code: "IT",
    name: "คณะเทคโนโลยีสารสนเทศและการสื่อสาร",
    nameEn: "Faculty of Information and Communication Technology",
    departments: [
      { code: "IT", name: "เทคโนโลยีสารสนเทศ", nameEn: "Information Technology" },
      { code: "TC", name: "วิศวกรรมโทรคมนาคม", nameEn: "Telecommunication Engineering" },
    ],
  },
  {
    code: "ER",
    name: "คณะสิ่งแวดล้อมและทรัพยากรศาสตร์",
    nameEn: "Faculty of Environment and Resource Studies",
    // ที่มา: en.mahidol.ac.th
    departments: [
      { code: "ET", name: "วิทยาศาสตร์และเทคโนโลยีสิ่งแวดล้อม (เอกเทคโนโลยีสิ่งแวดล้อม)", nameEn: "Environmental Science and Technology" },
      { code: "NM", name: "วิทยาศาสตร์และเทคโนโลยีสิ่งแวดล้อม (เอกการจัดการทรัพยากรฯ)", nameEn: "Natural Resources and Environmental Management" },
      { code: "IM", name: "การจัดการทรัพยากรธรรมชาติและสิ่งแวดล้อม (นานาชาติ)", nameEn: "Natural Resources and Environmental Management (International)" },
    ],
  },
  {
    code: "GS",
    name: "บัณฑิตวิทยาลัย",
    nameEn: "Graduate School",
    departments: [
      { code: "EN", name: "ภาษาอังกฤษ", nameEn: "English" },
      { code: "HM", name: "การบริหารสุขภาพ", nameEn: "Health Management" },
      { code: "HR", name: "สิทธิมนุษยชน", nameEn: "Human Rights" },
      { code: "IT", name: "เทคโนโลยีสารสนเทศ", nameEn: "Information Technology" },
      { code: "SE", name: "การศึกษาวิทยาศาสตร์", nameEn: "Science Education" },
    ],
  },
  // ── วิทยาลัย ────────────────────────────────────────────
  {
    code: "MU",
    name: "วิทยาลัยนานาชาติ",
    nameEn: "Mahidol University International College",
    departments: [
      { code: "BA", name: "บริหารธุรกิจ", nameEn: "Business Administration" },
      { code: "CS", name: "วิทยาการคอมพิวเตอร์", nameEn: "Computer Science" },
      { code: "IT", name: "เทคโนโลยีสารสนเทศ", nameEn: "Information Technology" },
      { code: "MC", name: "การสื่อสารมวลชน", nameEn: "Mass Communication" },
      { code: "TM", name: "การจัดการการท่องเที่ยว", nameEn: "Tourism Management" },
    ],
  },
  {
    code: "CM",
    name: "วิทยาลัยการจัดการ",
    nameEn: "College of Management",
    departments: [
      { code: "MM", name: "การจัดการมหาวิทยาลัย", nameEn: "University Management" },
      { code: "MB", name: "การบริหารธุรกิจ", nameEn: "Business Administration" },
    ],
  },
  {
    code: "MU",
    name: "วิทยาลัยดุริยางคศิลป์",
    nameEn: "College of Music",
    departments: [
      { code: "MU", name: "ดุริยางคศิลป์", nameEn: "Music" },
    ],
  },
  {
    code: "RS",
    name: "วิทยาลัยราชสุดา",
    nameEn: "Ratchasuda College",
    departments: [
      { code: "RS", name: "การศึกษาสำหรับคนพิการ", nameEn: "Special Education" },
    ],
  },
  {
    code: "SS",
    name: "วิทยาลัยวิทยาศาสตร์และเทคโนโลยีการกีฬา",
    nameEn: "College of Sports Science and Technology",
    departments: [
      { code: "SS", name: "วิทยาศาสตร์การกีฬา", nameEn: "Sports Science" },
      { code: "ST", name: "เทคโนโลยีการกีฬา", nameEn: "Sports Technology" },
    ],
  },
  {
    code: "CR",
    name: "วิทยาลัยศาสนศึกษา",
    nameEn: "College of Religious Studies",
    departments: [
      { code: "CR", name: "ศาสนศึกษา", nameEn: "Religious Studies" },
    ],
  },
];

export function facultyName(code?: string): string {
  if (!code) return "—";
  const f = FACULTIES.find((x) => x.code === code);
  return f ? f.name : code;
}

export function departmentName(facCode?: string, deptCode?: string): string {
  if (!facCode || !deptCode) return "—";
  const f = FACULTIES.find((x) => x.code === facCode);
  const d = f?.departments.find((x) => x.code === deptCode);
  return d ? d.name : deptCode;
}

// ★ แสดงเป็นประโยคคนอ่านรู้เรื่อง: "คณะวิศวกรรมศาสตร์ · สาขาวิชาวิศวกรรมคอมพิวเตอร์"
// ถ้ามีแค่คณะ → "คณะวิศวกรรมศาสตร์" อย่างเดียว ไม่แปะรหัสมั่ว
export function facultyFullLabel(facCode?: string, deptCode?: string): string {
  if (!facCode) return "—";
  const f = FACULTIES.find((x) => x.code === facCode);
  if (!f) return facCode;
  if (!deptCode) return f.name;
  const d = f.departments.find((x) => x.code === deptCode);
  return d ? `${f.name} · ${d.name}` : f.name;
}

// ★ ข้อมูลแสดงผลพร้อมกันทั้งชื่อไทย(กระชับ) รหัส และชื่ออังกฤษ
// ใช้ในหน้าโปรไฟล์ — ตัดคำนำหน้า "คณะ/สาขาวิชา" ออกเพื่อไม่ให้ซ้ำกับ label หรือ title การ์ด
export function facultyDisplay(facCode?: string, deptCode?: string) {
  const f = facCode ? FACULTIES.find((x) => x.code === facCode) : undefined;
  const d = f && deptCode ? f.departments.find((x) => x.code === deptCode) : undefined;
  const facultyThaiShort = f ? f.name.replace(/^คณะ\s*/, "") : (facCode ?? "");
  const deptThaiShort = d ? d.name.replace(/^(สาขาวิชา|สาขาเน้น)\s*/, "") : (deptCode ?? "");
  const deptAbbr = d ? (d.abbr ?? `${f?.code ?? ""}${d.code}`) : (deptCode ?? "");
  return {
    facultyThai: f?.name ?? facCode ?? "—",
    facultyThaiShort: facultyThaiShort || "—",
    facultyEn: f?.nameEn ?? "",
    facultyCode: f?.code ?? facCode ?? "",
    deptThai: d?.name ?? deptCode ?? "—",
    deptThaiShort: deptThaiShort || "—",
    deptEn: d?.nameEn ?? "",
    deptAbbr,
  };
}
