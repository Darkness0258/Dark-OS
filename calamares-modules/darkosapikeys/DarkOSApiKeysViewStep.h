// SPDX-License-Identifier: GPL-3.0-or-later

#ifndef DARKOS_API_KEYS_VIEW_STEP_H
#define DARKOS_API_KEYS_VIEW_STEP_H

#include "DllMacro.h"
#include "utils/PluginFactory.h"
#include "viewpages/ViewStep.h"

class ApiKeysPage;

class PLUGINDLLEXPORT DarkOSApiKeysViewStep final : public Calamares::ViewStep
{
    Q_OBJECT

public:
    explicit DarkOSApiKeysViewStep( QObject* parent = nullptr );
    ~DarkOSApiKeysViewStep() override;

    QString prettyName() const override;
    QString prettyStatus() const override;
    QWidget* widget() override;

    bool isNextEnabled() const override;
    bool isBackEnabled() const override;
    bool isAtBeginning() const override;
    bool isAtEnd() const override;

    Calamares::JobList jobs() const override;
    void onCancel() override;

private:
    ApiKeysPage* m_widget;
};

CALAMARES_PLUGIN_FACTORY_DECLARATION( DarkOSApiKeysViewStepFactory )

#endif  // DARKOS_API_KEYS_VIEW_STEP_H
