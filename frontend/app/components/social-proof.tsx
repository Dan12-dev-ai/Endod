export default function SocialProof() {
  return (
    <section className="bg-[#f5f3ef] py-14 border-t border-b border-stone-200" data-purpose="partner-logos-bar">
      <div className="max-w-7xl mx-auto px-6 sm:px-12 text-center">
        <p className="text-[12px] font-semibold uppercase tracking-[0.18em] text-stone-600 mb-10">
          ONE SYSTEM FOR PATIENTS, DOCTORS, NURSES &amp; HOSPITAL ADMINS
        </p>
        {/* User Role Badges */}
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-8 items-center justify-items-center opacity-85">
          {/* Patients */}
          <div className="flex items-center gap-2 text-slate-900">
            <svg className="w-6 h-6" fill="currentColor" viewBox="0 0 24 24">
              <path d="M12 2a5 5 0 1 0 0 10 5 5 0 0 0 0-10zm0 12c-5 0-9 2.5-9 5.5V22h18v-2.5C21 16.5 17 14 12 14z" />
            </svg>
            <span className="font-sans text-[13px] font-semibold">Patients</span>
          </div>

          {/* Doctors */}
          <div className="flex items-center gap-2 text-slate-900">
            <svg className="w-6 h-6" fill="currentColor" viewBox="0 0 24 24">
              <path d="M12 2a5 5 0 1 0 0 10 5 5 0 0 0 0-10zm0 12c-4 0-8 2-8 4.5V21h16v-2.5c0-2.5-4-4.5-8-4.5zm4-9h2v3h3v2h-3v3h-2v-3h-3V8h3z" />
            </svg>
            <span className="font-sans text-[13px] font-semibold">Doctors</span>
          </div>

          {/* Nurses */}
          <div className="flex items-center gap-2 text-slate-900">
            <svg className="w-6 h-6" fill="currentColor" viewBox="0 0 24 24">
              <path d="M12 2a5 5 0 1 0 0 10 5 5 0 0 0 0-10zm0 12c-4 0-8 2-8 4.5V21h16v-2.5c0-2.5-4-4.5-8-4.5zm-1-4h2v2h2v2h-2v2h-2v-2H9v-2h2z" />
            </svg>
            <span className="font-sans text-[13px] font-semibold">Nurses</span>
          </div>

          {/* Receptionists */}
          <div className="flex items-center gap-2 text-slate-900">
            <svg className="w-6 h-6" fill="currentColor" viewBox="0 0 24 24">
              <path d="M20 6h-4V4a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v2H4a2 2 0 0 0-2 2v11a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2zm-10-2h4v2h-4V4z" />
            </svg>
            <span className="font-sans text-[13px] font-semibold">Receptionists</span>
          </div>

          {/* Hospital Admins */}
          <div className="flex items-center gap-2 text-slate-900">
            <svg className="w-6 h-6" fill="currentColor" viewBox="0 0 24 24">
              <path d="M5 3v18l7-3 7 3V3H5zm12 2v12l-5-2.2L7 17V5h10z" />
            </svg>
            <span className="font-sans text-[13px] font-semibold">Admins</span>
          </div>

          {/* Hospitals */}
          <div className="flex items-center gap-2 text-slate-900">
            <svg className="w-6 h-6" fill="currentColor" viewBox="0 0 24 24">
              <path d="M10 2h4v6h6v6h-4v8h-4v-8H6V8h4V2z" />
            </svg>
            <span className="font-sans text-[13px] font-semibold">Hospitals</span>
          </div>
        </div>
      </div>
    </section>
  );
}
