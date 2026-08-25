// SPDX-License-Identifier: GPL-3.0-or-later

#ifndef DARKOS_WRITE_API_KEYS_JOB_H
#define DARKOS_WRITE_API_KEYS_JOB_H

#include "Job.h"

#include <QString>

class WriteApiKeysJob final : public Calamares::Job
{
public:
    WriteApiKeysJob( QString openRouterKey, QString groqKey );
    ~WriteApiKeysJob() override;

    QString prettyName() const override;
    QString prettyStatusMessage() const override;
    Calamares::JobResult exec() override;

private:
    void clearSecrets() noexcept;

    QString m_openRouterKey;
    QString m_groqKey;
};

#endif  // DARKOS_WRITE_API_KEYS_JOB_H
